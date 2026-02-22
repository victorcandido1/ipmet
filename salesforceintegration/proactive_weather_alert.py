"""
Alerta Proativo de Meteorologia - REVO
Cruza voos das proximas horas com previsoes TAF
Dispara alertas quando ha risco de condicoes adversas
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class ProactiveWeatherAlert:
    """
    Monitora voos proximos e cruza com TAF para alertar sobre riscos
    """
    
    RISK_LEVELS = {
        'HIGH': '🔴 ALTO',
        'MEDIUM': '🟠 MEDIO', 
        'LOW': '🟡 BAIXO',
        'OK': '🟢 OK'
    }
    
    ADVERSE_PHENOMENA = {
        'TS': ('Trovoada', 'HIGH'),
        'TSRA': ('Trovoada com chuva', 'HIGH'),
        '+TSRA': ('Trovoada forte', 'HIGH'),
        'TSGR': ('Trovoada com granizo', 'HIGH'),
        '+RA': ('Chuva forte', 'MEDIUM'),
        'SHRA': ('Pancadas de chuva', 'MEDIUM'),
        '+SHRA': ('Pancadas fortes', 'HIGH'),
        'FG': ('Nevoeiro', 'HIGH'),
        'MIFG': ('Nevoeiro raso', 'MEDIUM'),
        'BCFG': ('Nevoeiro em bancos', 'MEDIUM'),
        'BR': ('Nevoa umida', 'LOW'),
        'SQ': ('Tempestade', 'HIGH'),
        'FC': ('Tornado', 'HIGH'),
        'VCTS': ('Trovoadas proximas', 'MEDIUM'),
        'VCSH': ('Pancadas proximas', 'LOW'),
    }
    
    def __init__(self, weather_monitor, telegram_notifier):
        self.weather_monitor = weather_monitor
        self.notifier = telegram_notifier
        self.hours_ahead = 4
    
    def get_flights_next_hours(self, voos: List[Dict], hours: int = 4) -> List[Dict]:
        """Retorna voos nas proximas N horas"""
        agora = datetime.now(timezone.utc)
        limite = agora + timedelta(hours=hours)
        
        voos_proximos = []
        for voo in voos:
            dt_str = voo.get('DataHoraVoo__c', '')
            if not dt_str:
                continue
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                if agora <= dt <= limite:
                    voos_proximos.append(voo)
            except:
                pass
        
        return sorted(voos_proximos, key=lambda v: v.get('DataHoraVoo__c', ''))
    
    def extract_route_airports(self, voo: Dict) -> List[str]:
        """Extrai ICAOs da rota do voo"""
        rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or ''
        icaos = []
        
        for part in str(rota).replace('>', ' ').replace('-', ' ').split():
            part = part.strip().upper()
            if len(part) == 4 and part.isalpha():
                icaos.append(part)
        
        return icaos
    
    def parse_taf_periods(self, taf_data: Dict) -> List[Dict]:
        """Extrai periodos do TAF com horarios e condicoes"""
        periods = []
        
        fcsts = taf_data.get('fcsts', [])
        for fcst in fcsts:
            period = {
                'from_time': None,
                'to_time': None,
                'type': fcst.get('fcstChange', 'FM'),
                'visibility_m': None,
                'ceiling_ft': None,
                'weather': [],
                'probability': fcst.get('probability'),
                'is_tempo': fcst.get('fcstChange') == 'TEMPO',
                'is_prob': fcst.get('fcstChange') == 'PROB' or fcst.get('probability') is not None,
                'risk_level': 'OK',
                'risk_reasons': []
            }
            
            time_from = fcst.get('timeFrom')
            time_to = fcst.get('timeTo')
            
            if time_from:
                try:
                    if isinstance(time_from, (int, float)):
                        period['from_time'] = datetime.fromtimestamp(time_from, tz=timezone.utc)
                    elif isinstance(time_from, str):
                        period['from_time'] = datetime.fromisoformat(time_from.replace('Z', '+00:00'))
                except:
                    pass
            
            if time_to:
                try:
                    if isinstance(time_to, (int, float)):
                        period['to_time'] = datetime.fromtimestamp(time_to, tz=timezone.utc)
                    elif isinstance(time_to, str):
                        period['to_time'] = datetime.fromisoformat(time_to.replace('Z', '+00:00'))
                except:
                    pass
            
            vis = fcst.get('visib')
            if vis:
                if isinstance(vis, (int, float)):
                    period['visibility_m'] = int(vis * 1609.34) if vis < 20 else int(vis)
                elif isinstance(vis, str):
                    if vis == '6+' or vis == 'P6SM':
                        period['visibility_m'] = 10000
                    elif vis.replace('.','').replace('/','').isdigit():
                        v = float(vis.split('/')[0]) if '/' in vis else float(vis)
                        period['visibility_m'] = int(v * 1609.34) if v < 20 else int(v)
            
            clouds = fcst.get('clouds', [])
            for cloud in clouds:
                if isinstance(cloud, dict):
                    cover = cloud.get('cover', '')
                    base = cloud.get('base')
                    if cover in ['BKN', 'OVC', 'VV'] and base:
                        base_ft = base if base > 100 else base * 100
                        if period['ceiling_ft'] is None or base_ft < period['ceiling_ft']:
                            period['ceiling_ft'] = base_ft
            
            wx = fcst.get('wxString', '')
            if wx:
                period['weather'] = [w.strip() for w in str(wx).split() if w.strip()]
            
            self._evaluate_period_risk(period)
            periods.append(period)
        
        return periods
    
    def _evaluate_period_risk(self, period: Dict):
        """Avalia nivel de risco de um periodo do TAF"""
        risks = []
        max_risk = 'OK'
        
        for wx in period['weather']:
            if wx in self.ADVERSE_PHENOMENA:
                desc, level = self.ADVERSE_PHENOMENA[wx]
                risks.append(f"{desc}")
                if level == 'HIGH':
                    max_risk = 'HIGH'
                elif level == 'MEDIUM' and max_risk != 'HIGH':
                    max_risk = 'MEDIUM'
                elif level == 'LOW' and max_risk == 'OK':
                    max_risk = 'LOW'
        
        vis = period['visibility_m']
        if vis:
            if vis < 1000:
                risks.append(f"Visibilidade muito baixa ({vis}m)")
                max_risk = 'HIGH'
            elif vis < 3000:
                risks.append(f"Visibilidade reduzida ({vis}m)")
                if max_risk != 'HIGH':
                    max_risk = 'MEDIUM'
            elif vis < 5000:
                risks.append(f"Visibilidade marginal ({vis}m)")
                if max_risk == 'OK':
                    max_risk = 'LOW'
        
        ceiling = period['ceiling_ft']
        if ceiling:
            if ceiling < 500:
                risks.append(f"Teto muito baixo ({ceiling}ft)")
                max_risk = 'HIGH'
            elif ceiling < 1000:
                risks.append(f"Teto baixo ({ceiling}ft)")
                if max_risk != 'HIGH':
                    max_risk = 'MEDIUM'
            elif ceiling < 1500:
                risks.append(f"Teto marginal ({ceiling}ft)")
                if max_risk == 'OK':
                    max_risk = 'LOW'
        
        if period['is_prob'] and period['probability']:
            prob = period['probability']
            if prob >= 40 and max_risk == 'HIGH':
                pass
            elif prob >= 30 and max_risk in ['HIGH', 'MEDIUM']:
                if max_risk == 'HIGH':
                    max_risk = 'MEDIUM'
        
        period['risk_level'] = max_risk
        period['risk_reasons'] = risks
    
    def analyze_flight_risk(self, voo: Dict, taf_by_icao: Dict, metar_by_icao: Dict) -> Dict:
        """Analisa risco meteorologico para um voo especifico"""
        
        dt_str = voo.get('DataHoraVoo__c', '')
        try:
            dt_voo = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
        
        prefixo = voo.get('PrefixoTexto__c') or voo.get('Prefixo__c') or '-'
        rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or '-'
        host = voo.get('ResponsavelpelaoperacaoTerrestre__c') or ''
        pax = voo.get('ContadorPassageiros__c') or 0
        
        icaos = self.extract_route_airports(voo)
        
        flight_risk = {
            'voo': voo,
            'prefixo': prefixo,
            'rota': rota,
            'host': host,
            'pax': pax,
            'hora_local': (dt_voo - timedelta(hours=3)).strftime('%H:%M'),
            'dt_voo': dt_voo,
            'icaos': icaos,
            'overall_risk': 'OK',
            'airport_risks': [],
            'current_conditions': [],
            'forecast_risks': []
        }
        
        max_risk = 'OK'
        
        for icao in icaos:
            metar = metar_by_icao.get(icao)
            if metar:
                cat = metar.get('flight_category', 'VFR')
                if cat == 'IFR':
                    flight_risk['current_conditions'].append(f"{icao}: IFR agora")
                    if max_risk != 'HIGH':
                        max_risk = 'MEDIUM'
                elif cat == 'LIFR':
                    flight_risk['current_conditions'].append(f"{icao}: LIFR agora")
                    max_risk = 'HIGH'
                
                if metar.get('is_ifr_closed'):
                    flight_risk['current_conditions'].append(f"{icao}: FECHADO para IFR")
                    max_risk = 'HIGH'
            
            taf = taf_by_icao.get(icao)
            if taf:
                periods = self.parse_taf_periods(taf)
                
                for period in periods:
                    p_from = period.get('from_time')
                    p_to = period.get('to_time')
                    
                    if not p_from or not p_to:
                        continue
                    
                    margin = timedelta(hours=2)
                    if p_from - margin <= dt_voo <= p_to + margin:
                        if period['risk_level'] != 'OK':
                            prob_str = f" ({period['probability']}% chance)" if period['is_prob'] else ""
                            tempo_str = " TEMPORARIO" if period['is_tempo'] else ""
                            
                            period_local_from = (p_from - timedelta(hours=3)).strftime('%H:%M')
                            period_local_to = (p_to - timedelta(hours=3)).strftime('%H:%M')
                            
                            risk_detail = {
                                'icao': icao,
                                'level': period['risk_level'],
                                'from': period_local_from,
                                'to': period_local_to,
                                'reasons': period['risk_reasons'],
                                'prob': period.get('probability'),
                                'is_tempo': period['is_tempo']
                            }
                            flight_risk['forecast_risks'].append(risk_detail)
                            
                            if period['risk_level'] == 'HIGH':
                                if not period['is_prob'] or period.get('probability', 0) >= 40:
                                    max_risk = 'HIGH'
                                elif max_risk != 'HIGH':
                                    max_risk = 'MEDIUM'
                            elif period['risk_level'] == 'MEDIUM':
                                if max_risk == 'OK':
                                    max_risk = 'MEDIUM' if not period['is_prob'] else 'LOW'
                            elif period['risk_level'] == 'LOW' and max_risk == 'OK':
                                max_risk = 'LOW'
        
        flight_risk['overall_risk'] = max_risk
        return flight_risk
    
    def check_upcoming_flights(self, voos_hoje: List[Dict], voos_amanha: List[Dict] = None) -> List[Dict]:
        """Verifica voos nas proximas horas e retorna alertas"""
        
        all_voos = (voos_hoje or []) + (voos_amanha or [])
        voos_proximos = self.get_flights_next_hours(all_voos, hours=self.hours_ahead)
        
        if not voos_proximos:
            return []
        
        weather_data = self.weather_monitor.check_weather()
        
        metar_by_icao = {}
        for metar in weather_data.get('metars', []):
            metar_by_icao[metar.get('icao')] = metar
        
        taf_by_icao = {}
        for taf in weather_data.get('tafs', []):
            taf_by_icao[taf.get('icao')] = taf
        
        alerts = []
        for voo in voos_proximos:
            risk = self.analyze_flight_risk(voo, taf_by_icao, metar_by_icao)
            if risk and risk['overall_risk'] != 'OK':
                alerts.append(risk)
        
        return alerts
    
    def format_proactive_alert(self, alerts: List[Dict]) -> str:
        """Formata mensagem de alerta proativo para Telegram"""
        
        if not alerts:
            return None
        
        lines = ["<b>⚠️ ALERTA METEOROLOGICO - VOOS PROXIMOS</b>"]
        lines.append(f"📅 {datetime.now().strftime('%d/%m %H:%M')}")
        lines.append("")
        
        high_risk = [a for a in alerts if a['overall_risk'] == 'HIGH']
        medium_risk = [a for a in alerts if a['overall_risk'] == 'MEDIUM']
        low_risk = [a for a in alerts if a['overall_risk'] == 'LOW']
        
        if high_risk:
            lines.append("<b>🔴 RISCO ALTO</b>")
            for alert in high_risk:
                lines.extend(self._format_single_alert(alert))
            lines.append("")
        
        if medium_risk:
            lines.append("<b>🟠 RISCO MEDIO</b>")
            for alert in medium_risk:
                lines.extend(self._format_single_alert(alert))
            lines.append("")
        
        if low_risk:
            lines.append("<b>🟡 ATENCAO</b>")
            for alert in low_risk:
                lines.extend(self._format_single_alert(alert, brief=True))
            lines.append("")
        
        lines.append("<i>Monitore TAF e METAR para atualizacoes</i>")
        
        return "\n".join(lines)
    
    def _format_single_alert(self, alert: Dict, brief: bool = False) -> List[str]:
        """Formata um alerta individual"""
        lines = []
        
        prefixo = str(alert.get('prefixo', '-')).replace('<', '').replace('>', '')
        rota = str(alert.get('rota', '-')).replace('<', '').replace('>', '').replace('>', '-')
        rota_parts = rota.split('-')
        if len(rota_parts) >= 2:
            rota = f"{rota_parts[0].strip()}-{rota_parts[-1].strip()}"
        
        hora = alert.get('hora_local', '--:--')
        host = alert.get('host', '')
        host_str = f" | {host}" if host else ""
        
        lines.append(f"<b>{hora} {prefixo}</b> | {rota}{host_str}")
        
        if not brief:
            for cond in alert.get('current_conditions', []):
                lines.append(f"   ❗ {cond}")
            
            for risk in alert.get('forecast_risks', []):
                icao = risk['icao']
                level_emoji = '🔴' if risk['level'] == 'HIGH' else '🟠' if risk['level'] == 'MEDIUM' else '🟡'
                
                time_range = f"{risk['from']}-{risk['to']}"
                reasons = ", ".join(risk['reasons'][:2])
                
                prob_str = ""
                if risk.get('prob'):
                    prob_str = f" ({risk['prob']}% chance)"
                
                tempo_str = " [TEMPO]" if risk.get('is_tempo') else ""
                
                lines.append(f"   {level_emoji} {icao} {time_range}: {reasons}{prob_str}{tempo_str}")
        else:
            all_reasons = []
            for risk in alert.get('forecast_risks', []):
                all_reasons.extend(risk['reasons'][:1])
            if all_reasons:
                unique_reasons = list(set(all_reasons))[:3]
                lines.append(f"   → {', '.join(unique_reasons)}")
        
        return lines
    
    def send_proactive_alerts(self, voos_hoje: List[Dict], voos_amanha: List[Dict] = None) -> bool:
        """Verifica e envia alertas proativos"""
        
        alerts = self.check_upcoming_flights(voos_hoje, voos_amanha)
        
        if not alerts:
            logging.info("Nenhum alerta meteorologico para voos proximos")
            return False
        
        high_count = len([a for a in alerts if a['overall_risk'] == 'HIGH'])
        medium_count = len([a for a in alerts if a['overall_risk'] == 'MEDIUM'])
        
        logging.info(f"Alertas encontrados: {high_count} alto, {medium_count} medio, {len(alerts) - high_count - medium_count} baixo")
        
        message = self.format_proactive_alert(alerts)
        
        if message:
            return self.notifier.send_message(message)
        
        return False


def main():
    """Teste do modulo de alertas proativos"""
    from telegram_notifier import TelegramNotifier, get_voos_salesforce
    from weather_monitor import WeatherMonitor
    
    print("Iniciando teste de alertas proativos...")
    
    notifier = TelegramNotifier()
    weather_monitor = WeatherMonitor()
    proactive = ProactiveWeatherAlert(weather_monitor, notifier)
    
    print("Buscando voos...")
    voos_hoje, voos_amanha, _voos_depois, _voos_proximos = get_voos_salesforce()
    print(f"Encontrados: {len(voos_hoje)} hoje, {len(voos_amanha)} amanha")
    
    print(f"\nVoos nas proximas {proactive.hours_ahead} horas:")
    all_voos = voos_hoje + voos_amanha
    proximos = proactive.get_flights_next_hours(all_voos, hours=proactive.hours_ahead)
    for v in proximos:
        dt = v.get('DataHoraVoo__c', '')
        try:
            dt_local = datetime.fromisoformat(dt.replace('Z', '+00:00')) - timedelta(hours=3)
            hora = dt_local.strftime('%H:%M')
        except:
            hora = '--:--'
        prefixo = v.get('PrefixoTexto__c', '-')
        rota = v.get('RotaAbreviada__c', '-')
        print(f"  {hora} {prefixo} | {rota}")
    
    print("\nAnalisando riscos meteorologicos...")
    alerts = proactive.check_upcoming_flights(voos_hoje, voos_amanha)
    
    if alerts:
        print(f"\n⚠️ {len(alerts)} voo(s) com alertas:")
        for alert in alerts:
            print(f"\n  {alert['hora_local']} {alert['prefixo']} - Risco: {alert['overall_risk']}")
            for cond in alert.get('current_conditions', []):
                print(f"    - {cond}")
            for risk in alert.get('forecast_risks', []):
                print(f"    - {risk['icao']} {risk['from']}-{risk['to']}: {', '.join(risk['reasons'])}")
        
        print("\n" + "="*50)
        print("Mensagem formatada:")
        print("="*50)
        msg = proactive.format_proactive_alert(alerts)
        print(msg.replace('<b>', '**').replace('</b>', '**').replace('<i>', '_').replace('</i>', '_'))
    else:
        print("\n✅ Nenhum voo com risco meteorologico nas proximas horas")
    
    resposta = input("\nEnviar alerta para Telegram? (s/n): ")
    if resposta.lower() == 's':
        proactive.send_proactive_alerts(voos_hoje, voos_amanha)
        print("Alerta enviado!")


if __name__ == "__main__":
    main()
