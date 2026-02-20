"""
Monitor de Voos - REVO
Executa verificações periódicas e envia notificações
Inclui monitoramento meteorológico (METAR/TAF/SPECI)
"""

import os
import time
import schedule
from datetime import datetime
from telegram_notifier import TelegramNotifier
from salesforce_extractor import SalesforceExtractor
from weather_monitor import WeatherMonitor
from proactive_weather_alert import ProactiveWeatherAlert
from state_manager import get_state_manager
from logger import setup_logging
import pandas as pd

logging = setup_logging('flight_monitor')

class FlightMonitor:
    def __init__(self):
        self.notifier = TelegramNotifier()
        self.extractor = SalesforceExtractor()
        self.weather_monitor = WeatherMonitor()
        self.proactive_alert = ProactiveWeatherAlert(self.weather_monitor, self.notifier)
        self.state_manager = get_state_manager()
        self.data_file = 'dados_reservas.csv'
        self.last_weather_alerts = self.state_manager.load_weather_state()
        self.last_proactive_check = self.state_manager.load_proactive_state()
    
    def _save_proactive_state(self, alerts_sent):
        """Salva estado dos alertas proativos"""
        self.state_manager.save_proactive_state(alerts_sent)
    
    def _save_weather_state(self):
        """Salva estado dos alertas meteorologicos"""
        self.state_manager.save_weather_state(self.last_weather_alerts)
    
    def refresh_data_from_csv(self, csv_path):
        """Atualiza dados a partir de um CSV"""
        try:
            self.extractor.run_from_csv(csv_path)
            logging.info("Dados atualizados do CSV")
            return True
        except Exception as e:
            logging.error(f"Erro ao atualizar dados: {e}")
            return False
    
    def check_changes(self):
        """Verifica mudanças nos dados"""
        logging.info("Iniciando verificação de mudanças...")
        
        try:
            if not os.path.exists(self.data_file):
                logging.warning(f"Arquivo {self.data_file} não encontrado")
                return
            
            df = pd.read_csv(self.data_file, encoding='utf-8-sig')
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            
            novos, cancelados = self.notifier.check_for_changes(df)
            logging.info(f"Verificação concluída: {novos} novos, {cancelados} cancelados")
            
        except Exception as e:
            logging.error(f"Erro na verificação: {e}")
    
    def check_weather(self):
        """Verifica condições meteorológicas e envia alertas"""
        logging.info("Verificando condições meteorológicas...")
        
        try:
            weather_data = self.weather_monitor.check_weather()
            
            specis = self.weather_monitor.has_speci(weather_data)
            weather_images = None
            if specis:
                logging.info(f"SPECI detectado em {len(specis)} aeroporto(s) - buscando imagens...")
                weather_images = self.weather_monitor.get_weather_images_for_speci()
            
            current_alerts = set()
            for alert in weather_data.get("alerts", []):
                alert_key = f"{alert['icao']}_{alert['type']}_{alert['category']}"
                current_alerts.add(alert_key)
                
                if alert_key not in self.last_weather_alerts:
                    images_to_send = weather_images if alert.get("type") == "SPECI" else None
                    self.notifier.send_weather_alert(alert, images=images_to_send)
                    logging.info(f"Alerta meteorológico enviado: {alert['icao']} - {alert['category']}")
            
            self.last_weather_alerts = current_alerts
            self._save_weather_state()
            
            alerts_count = len(weather_data.get("alerts", []))
            if alerts_count > 0:
                logging.info(f"Verificação meteorológica: {alerts_count} alertas ativos")
            else:
                logging.info("Verificação meteorológica: sem alertas")
                
        except Exception as e:
            logging.error(f"Erro na verificação meteorológica: {e}")
    
    def send_weather_summary(self):
        """Envia resumo meteorológico completo"""
        logging.info("Enviando resumo meteorológico...")
        
        try:
            weather_data = self.weather_monitor.check_weather()
            
            if self.notifier.send_weather_summary(weather_data):
                logging.info("Resumo meteorológico enviado com sucesso")
            else:
                logging.error("Falha ao enviar resumo meteorológico")
                
        except Exception as e:
            logging.error(f"Erro ao enviar resumo meteorológico: {e}")
    
    def send_daily_summary(self):
        """Envia resumo diário"""
        logging.info("Enviando resumo diário...")
        
        try:
            if not os.path.exists(self.data_file):
                logging.warning(f"Arquivo {self.data_file} não encontrado")
                return
            
            df = pd.read_csv(self.data_file, encoding='utf-8-sig')
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            
            if self.notifier.generate_daily_summary(df):
                logging.info("Resumo diário enviado com sucesso")
            else:
                logging.error("Falha ao enviar resumo diário")
                
        except Exception as e:
            logging.error(f"Erro ao enviar resumo: {e}")
    
    def send_morning_briefing(self):
        """Envia briefing matinal completo (voos + meteorologia + imagens)"""
        logging.info("Enviando briefing matinal...")

        try:
            from telegram_notifier import get_voos_salesforce

            voos_hoje, voos_amanha, voos_depois_amanha = get_voos_salesforce()
            logging.info(f"Voos encontrados: {len(voos_hoje)} hoje, {len(voos_amanha)} amanha, {len(voos_depois_amanha)} depois de amanha")

            weather_data = self.weather_monitor.check_weather()

            if self.notifier.send_morning_briefing(voos_hoje, voos_amanha, weather_data, voos_depois_amanha):
                logging.info("Briefing matinal enviado com sucesso")
            else:
                logging.error("Falha ao enviar briefing matinal")

            logging.info("Enviando imagens meteorologicas do briefing...")
            self.send_weather_images()

        except Exception as e:
            logging.error(f"Erro ao enviar briefing: {e}")
    
    def send_weather_images(self):
        """Envia imagens meteorologicas (radar, satelite, nuvens, cartas REDEMET, webcams)"""
        logging.info("Enviando imagens meteorologicas...")
        
        try:
            from weather_images import WeatherImagesClient
            
            images_client = WeatherImagesClient()
            images = images_client.get_weather_update_package()
            
            weather_data = self.weather_monitor.check_weather()
            
            caption_base = f"Atualizacao Meteorologica - {datetime.now().strftime('%H:%M')}\n"
            
            has_alerts = any(m.get("is_ifr_closed") for m in weather_data.get("metars", []))
            if has_alerts:
                caption_base += "ALERTAS ATIVOS - Verificar condicoes!\n"
            
            captions = {
                "radar_gif": f"{caption_base}Radar IPMET - Evolucao (GIF animado)",
                "satelite_gif": f"{caption_base}Satelite IPMET - Evolucao (GIF animado)",
                "sigwx": f"{caption_base}SIGWX Inferior (SUP-FL250)\nFenomenos significativos baixa altitude",
                "indice_k": f"{caption_base}Indice K - Potencial Tempestades\nK>30: Alta prob. | K>35: Severas",
                "ventos_850": f"{caption_base}Ventos 850 hPa (~1500m)\nAltitude cruzeiro helicopteros",
                "radar": f"{caption_base}Radar Meteorologico - SP (Windy)",
                "satelite": f"{caption_base}Satelite GOES-16 (GEOCOLOR)",
                "nuvens": f"{caption_base}Infravermelho - Nuvens",
                "webcam_sbgr": f"{caption_base}Webcam SBGR - Guarulhos (YouTube)",
                "webcam_sbsp": f"{caption_base}Webcam SBSP - Congonhas (YouTube)",
                "webcam_helipark": f"{caption_base}Webcam Helipark",
            }
            
            sent_count = 0
            for name, path in images.items():
                if path and os.path.exists(path):
                    caption = captions.get(name, f"{caption_base}{name}")
                    
                    if path.endswith('.gif') and 'ipmet' in path.lower():
                        if self.notifier.send_animation(path, caption):
                            sent_count += 1
                            logging.info(f"GIF animado enviado: {name}")
                    else:
                        if self.notifier.send_photo(path, caption):
                            sent_count += 1
                            logging.info(f"Imagem enviada: {name}")
            
            logging.info(f"Imagens meteorologicas enviadas: {sent_count}")
            
        except Exception as e:
            logging.error(f"Erro ao enviar imagens meteorologicas: {e}")
    
    def check_proactive_weather_alerts(self):
        """Verifica e envia alertas proativos para voos nas proximas horas"""
        logging.info("Verificando alertas proativos para voos proximos...")
        
        try:
            from telegram_notifier import get_voos_salesforce
            
            voos_hoje, voos_amanha, voos_depois_amanha = get_voos_salesforce()

            todos_proximos = list(voos_hoje) + list(voos_amanha) + list(voos_depois_amanha)
            alerts = self.proactive_alert.check_upcoming_flights(voos_hoje, voos_amanha)
            
            if not alerts:
                logging.info("Nenhum voo proximo com risco meteorologico")
                return
            
            high_risk = [a for a in alerts if a['overall_risk'] == 'HIGH']
            medium_risk = [a for a in alerts if a['overall_risk'] == 'MEDIUM']
            
            new_alerts = {}
            for alert in alerts:
                voo_id = f"{alert['prefixo']}_{alert['hora_local']}_{alert['rota']}"
                new_alerts[voo_id] = alert['overall_risk']
            
            alerts_to_send = []
            for alert in alerts:
                voo_id = f"{alert['prefixo']}_{alert['hora_local']}_{alert['rota']}"
                prev_risk = self.last_proactive_check.get(voo_id)
                
                if not prev_risk or alert['overall_risk'] == 'HIGH' or \
                   (alert['overall_risk'] == 'MEDIUM' and prev_risk == 'LOW'):
                    alerts_to_send.append(alert)
            
            if alerts_to_send:
                logging.info(f"Enviando alertas proativos: {len(alerts_to_send)} novos/agravados")
                msg = self.proactive_alert.format_proactive_alert(alerts_to_send)
                if msg:
                    self.notifier.send_message(msg)
            else:
                logging.info("Nenhum alerta novo ou agravado para enviar")
            
            self._save_proactive_state(new_alerts)
            self.last_proactive_check = new_alerts
                
        except Exception as e:
            logging.error(f"Erro ao verificar alertas proativos: {e}")
    
    def run_scheduled(self, include_weather=True):
        """Executa o monitor com agendamento"""
        logging.info("=" * 60)
        logging.info("INICIANDO MONITOR DE VOOS - REVO")
        logging.info("=" * 60)
        
        if not self.notifier.is_configured():
            logging.error("Telegram não configurado. Execute: python telegram_notifier.py --setup")
            return
        
        schedule.every(15).minutes.do(self.check_changes)
        
        schedule.every().day.at("06:00").do(self.send_morning_briefing)
        
        schedule.every().day.at("18:00").do(self.send_daily_summary)
        
        if include_weather:
            schedule.every(30).minutes.do(self.check_weather)
            
            schedule.every().day.at("09:00").do(self.send_weather_images)
            schedule.every().day.at("12:00").do(self.send_weather_images)
            schedule.every().day.at("15:00").do(self.send_weather_images)
            schedule.every().day.at("17:00").do(self.send_weather_images)
            
            schedule.every(2).hours.do(self.check_proactive_weather_alerts)
        
        logging.info("Agendamentos configurados:")
        logging.info("  - Verificação de mudanças: a cada 15 minutos")
        logging.info("  - BRIEFING MATINAL (voos + meteo): 06:00")
        logging.info("  - Resumo diário: 18:00")
        if include_weather:
            logging.info("  - Verificação meteorológica (alertas): a cada 30 minutos")
            logging.info("  - IMAGENS METEO (radar/satelite/nuvens): 09:00, 12:00, 15:00, 17:00")
            logging.info("  - ALERTAS PROATIVOS (voos proximos): a cada 2 horas")
        logging.info("")
        logging.info("Pressione Ctrl+C para parar o monitor")
        logging.info("=" * 60)
        
        current_hour = datetime.now().hour
        if current_hour < 5 or current_hour > 7:
            self.send_morning_briefing()
        else:
            logging.info(f"Horario proximo ao briefing agendado (06:00) - aguardando schedule...")
        
        self.check_changes()
        if include_weather:
            self.check_weather()
            self.check_proactive_weather_alerts()
        
        try:
            while True:
                schedule.run_pending()
                self.notifier.process_commands()
                time.sleep(30)
        except KeyboardInterrupt:
            logging.info("Monitor encerrado pelo usuário")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor de Voos - REVO')
    parser.add_argument('--start', action='store_true', help='Inicia o monitor completo (voos + meteo)')
    parser.add_argument('--start-flights-only', action='store_true', help='Inicia monitor apenas de voos')
    parser.add_argument('--check-now', action='store_true', help='Executa verificação imediata de voos')
    parser.add_argument('--summary-now', action='store_true', help='Envia resumo imediato de voos')
    parser.add_argument('--weather-now', action='store_true', help='Verifica meteorologia e envia alertas')
    parser.add_argument('--weather-summary', action='store_true', help='Envia resumo meteorológico completo')
    parser.add_argument('--weather-images', action='store_true', help='Envia imagens meteo (radar/satelite/nuvens)')
    parser.add_argument('--proactive-alert', action='store_true', help='Verifica e envia alertas proativos para voos proximos')
    parser.add_argument('--briefing', action='store_true', help='Envia briefing matinal (voos + meteorologia)')
    parser.add_argument('--csv', type=str, help='Atualiza dados de um CSV antes de verificar')
    
    args = parser.parse_args()
    
    monitor = FlightMonitor()
    
    if args.csv:
        monitor.refresh_data_from_csv(args.csv)
    
    if args.check_now:
        monitor.check_changes()
    elif args.summary_now:
        monitor.send_daily_summary()
    elif args.weather_now:
        monitor.check_weather()
    elif args.weather_summary:
        monitor.send_weather_summary()
    elif args.weather_images:
        monitor.send_weather_images()
    elif args.proactive_alert:
        monitor.check_proactive_weather_alerts()
    elif args.briefing:
        monitor.send_morning_briefing()
    elif args.start:
        monitor.run_scheduled(include_weather=True)
    elif args.start_flights_only:
        monitor.run_scheduled(include_weather=False)
    else:
        print("Monitor de Voos e Meteorologia - REVO")
        print("")
        print("Opcoes:")
        print("  --start              Inicia monitor completo (voos + meteorologia)")
        print("  --start-flights-only Inicia monitor apenas de voos")
        print("  --briefing           Envia briefing matinal (voos + meteo)")
        print("  --check-now          Verifica mudancas de voos agora")
        print("  --summary-now        Envia resumo de voos agora")
        print("  --weather-now        Verifica meteorologia e envia alertas")
        print("  --weather-summary    Envia resumo meteorologico completo")
        print("  --weather-images     Envia imagens (radar/satelite/nuvens)")
        print("  --proactive-alert    Verifica alertas proativos para voos proximos")
        print("")
        print("Use --help para mais opcoes")


if __name__ == "__main__":
    main()
