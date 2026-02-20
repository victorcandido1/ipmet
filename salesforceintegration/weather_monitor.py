"""
Monitor Meteorologico - REVO
Monitora METAR, TAF e SPECI dos aeroportos de Sao Paulo
Fonte: NOAA Aviation Weather Center (aviationweather.gov)
Alerta quando condicoes indicam fechamento para IFR ou operacoes de helicoptero
Baseado no projeto SP_demand
"""

import requests
import json
import re
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

NOAA_API_BASE = "https://aviationweather.gov/api/data"
AIRPORTS = ["SBGR", "SBSP", "SBMT", "SBKP"]

AIRPORT_INFO = {
    "SBGR": {"name": "Guarulhos", "lat": -23.4356, "lon": -46.4731},
    "SBSP": {"name": "Congonhas", "lat": -23.6261, "lon": -46.6564},
    "SBMT": {"name": "Campo de Marte", "lat": -23.5092, "lon": -46.6378},
    "SBKP": {"name": "Viracopos", "lat": -23.0074, "lon": -47.1345},
}

HELI_MINIMUMS = {
    "ceiling_ft": 600,
    "visibility_m": 3000,
}

WEATHER_PHENOMENA = {
    "TS": "Trovoada",
    "TSRA": "Trovoada com chuva",
    "+TSRA": "Trovoada forte com chuva",
    "-TSRA": "Trovoada fraca com chuva",
    "RA": "Chuva",
    "+RA": "Chuva forte",
    "-RA": "Chuva fraca",
    "SHRA": "Pancada de chuva",
    "+SHRA": "Pancada forte",
    "-SHRA": "Pancada fraca",
    "DZ": "Chuvisco",
    "+DZ": "Chuvisco forte",
    "-DZ": "Chuvisco fraco",
    "FG": "Nevoeiro",
    "BR": "Nevoa umida",
    "HZ": "Nevoa seca",
    "MIFG": "Nevoeiro raso",
    "BCFG": "Nevoeiro em bancos",
    "PRFG": "Nevoeiro parcial",
    "FU": "Fumaca",
    "SQ": "Tempestade",
    "FC": "Tornado/Tromba d'agua",
    "VCSH": "Pancadas nas proximidades",
    "VCTS": "Trovoadas nas proximidades",
    "VCFG": "Nevoeiro nas proximidades",
}

CLOUD_TYPES = {
    "FEW": "Poucas (1-2/8)",
    "SCT": "Esparsas (3-4/8)",
    "BKN": "Nublado (5-7/8)",
    "OVC": "Encoberto (8/8)",
    "CLR": "Ceu limpo",
    "SKC": "Ceu limpo",
    "NSC": "Sem nuvens significativas",
    "NCD": "Sem nuvens detectadas",
    "VV": "Visibilidade vertical",
    "CB": "Cumulonimbus",
    "TCU": "Cumulus congestus",
    "CAVOK": "CAVOK",
}


class WeatherMonitor:
    def __init__(self, state_file: str = 'weather_state.json'):
        self.state_file = state_file
        self.airports = AIRPORTS
        self.noaa_base = NOAA_API_BASE
    
    def fetch_metars_json(self) -> List[Dict]:
        """Busca METARs em formato JSON do NOAA (decodificado)"""
        url = f"{self.noaa_base}/metar"
        params = {"ids": ",".join(self.airports), "format": "json"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def fetch_metars(self) -> str:
        """Busca METARs em formato raw do NOAA"""
        url = f"{self.noaa_base}/metar"
        params = {"ids": ",".join(self.airports), "format": "raw"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.text
    
    def fetch_tafs_json(self) -> List[Dict]:
        """Busca TAFs em formato JSON do NOAA (decodificado)"""
        url = f"{self.noaa_base}/taf"
        params = {"ids": ",".join(self.airports), "format": "json"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def fetch_tafs(self) -> str:
        """Busca TAFs em formato raw do NOAA"""
        url = f"{self.noaa_base}/taf"
        params = {"ids": ",".join(self.airports), "format": "raw"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.text
    
    def fetch_sigmets_brazil(self) -> List[Dict]:
        """
        Busca SIGMETs internacionais ativos para o Brasil
        Fonte: NOAA AWC - International SIGMETs
        """
        url = f"{self.noaa_base}/isigmet"
        params = {"format": "json"}
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            brazil_sigmets = [s for s in data if s.get('firId', '').startswith('SB')]
            
            sp_sigmets = []
            sp_lat_min, sp_lat_max = -25.0, -22.0
            sp_lon_min, sp_lon_max = -48.0, -44.0
            
            for sigmet in brazil_sigmets:
                coords = sigmet.get('coords', [])
                if coords:
                    for coord in coords:
                        if isinstance(coord, dict):
                            lat = coord.get('lat', 0)
                            lon = coord.get('lon', 0)
                            if sp_lat_min <= lat <= sp_lat_max and sp_lon_min <= lon <= sp_lon_max:
                                sp_sigmets.append(sigmet)
                                break
                else:
                    sp_sigmets.append(sigmet)
            
            return sp_sigmets if sp_sigmets else brazil_sigmets
            
        except Exception as e:
            logging.warning(f"Erro ao buscar SIGMETs: {e}")
            return []
    
    def parse_sigmet(self, sigmet_data: Dict) -> Dict:
        """Converte SIGMET JSON do NOAA para formato legivel"""
        hazard_names = {
            "TS": "TEMPESTADE",
            "TURB": "TURBULENCIA",
            "ICE": "GELO",
            "MTW": "ONDAS DE MONTANHA",
            "TC": "CICLONE TROPICAL",
            "VA": "CINZAS VULCANICAS",
            "DS": "TEMPESTADE DE AREIA",
            "SS": "TEMPESTADE DE AREIA",
        }
        
        qualifier_names = {
            "EMBD": "Embutido",
            "SEV": "Severo",
            "MOD": "Moderado",
            "OBSC": "Obscurecido",
            "SQL": "Linha de instabilidade",
            "FRQ": "Frequente",
            "ISOL": "Isolado",
        }
        
        hazard = sigmet_data.get('hazard', '')
        qualifier = sigmet_data.get('qualifier', '')
        
        hazard_text = hazard_names.get(hazard, hazard)
        qualifier_text = qualifier_names.get(qualifier, qualifier)
        
        base = sigmet_data.get('base')
        top = sigmet_data.get('top')
        
        level_text = ""
        if top:
            level_text = f"ate FL{top//100}"
        if base and top:
            level_text = f"FL{base//100}-FL{top//100}"
        
        return {
            "fir": sigmet_data.get('firId', ''),
            "fir_name": sigmet_data.get('firName', ''),
            "hazard": hazard,
            "hazard_text": hazard_text,
            "qualifier": qualifier,
            "qualifier_text": qualifier_text,
            "level": level_text,
            "valid_from": sigmet_data.get('validTimeFrom'),
            "valid_to": sigmet_data.get('validTimeTo'),
            "raw": sigmet_data.get('rawSigmet', ''),
            "coords": sigmet_data.get('coords', []),
        }
    
    def parse_noaa_metar(self, noaa_data: Dict) -> Dict:
        """Converte METAR JSON do NOAA para formato interno"""
        raw = noaa_data.get("rawOb", "")
        metar_type = noaa_data.get("metarType", "METAR")
        icao = noaa_data.get("icaoId", "")
        
        vis_raw = noaa_data.get("visib", "6+")
        if vis_raw == "6+":
            vis_m = 10000
            vis_str = ">10km"
        elif isinstance(vis_raw, (int, float)):
            vis_m = int(vis_raw * 1609.34)
            vis_str = f"{vis_raw} SM ({vis_m}m)"
        else:
            vis_m = 10000
            vis_str = str(vis_raw)
        
        clouds_raw = noaa_data.get("clouds", [])
        clouds = []
        clouds_decoded = []
        ceiling_ft = None
        
        for cloud in clouds_raw:
            cover = cloud.get("cover", "")
            base = cloud.get("base")
            
            if base:
                clouds.append(f"{cover}{base//100:03d}")
            else:
                clouds.append(cover)
            
            cover_name = CLOUD_TYPES.get(cover, cover)
            if base:
                clouds_decoded.append(f"{cover_name} a {base}ft")
                if cover in ["BKN", "OVC", "VV"] and ceiling_ft is None:
                    ceiling_ft = base
            else:
                clouds_decoded.append(cover_name)
        
        cover_field = noaa_data.get("cover", "")
        if cover_field == "CAVOK":
            vis_m = 10000
            vis_str = "CAVOK (>10km, sem nuvens baixas)"
        
        wx_raw = noaa_data.get("wxString", "")
        weather = []
        weather_decoded = []
        if wx_raw:
            for wx in wx_raw.split():
                weather.append(wx)
                weather_decoded.append(WEATHER_PHENOMENA.get(wx, wx))
        
        flight_cat = noaa_data.get("fltCat", "VFR")
        
        result = {
            "raw": raw,
            "type": metar_type,
            "icao": icao,
            "time": None,
            "wind_dir": noaa_data.get("wdir"),
            "wind_speed": noaa_data.get("wspd"),
            "wind_gust": noaa_data.get("wgst"),
            "visibility_m": vis_m,
            "visibility_str": vis_str,
            "weather": weather,
            "weather_decoded": weather_decoded,
            "clouds": clouds,
            "clouds_decoded": clouds_decoded,
            "ceiling_ft": ceiling_ft,
            "temperature": noaa_data.get("temp"),
            "dewpoint": noaa_data.get("dewp"),
            "pressure": noaa_data.get("altim"),
            "flight_category": flight_cat,
            "is_ifr_closed": False,
            "closure_reasons": [],
            "noaa_data": noaa_data,
        }
        
        time_match = re.search(r"(\d{6}Z)", raw)
        if time_match:
            result["time"] = time_match.group(1)
        
        result["is_ifr_closed"], result["closure_reasons"] = self._check_ifr_closure(result)
        
        return result
    
    def parse_metar(self, metar_text: str) -> Dict:
        """Parse de METAR a partir de texto raw (fallback)"""
        result = {
            "raw": metar_text,
            "type": "METAR",
            "icao": None,
            "time": None,
            "wind_dir": None,
            "wind_speed": None,
            "wind_gust": None,
            "visibility_m": None,
            "visibility_str": None,
            "weather": [],
            "weather_decoded": [],
            "clouds": [],
            "clouds_decoded": [],
            "ceiling_ft": None,
            "temperature": None,
            "dewpoint": None,
            "pressure": None,
            "flight_category": None,
            "is_ifr_closed": False,
            "closure_reasons": []
        }
        
        parts = metar_text.split()
        if not parts:
            return result
        
        idx = 0
        
        if parts[idx] in ["METAR", "SPECI"]:
            result["type"] = parts[idx]
            idx += 1
        
        if idx < len(parts) and len(parts[idx]) == 4:
            result["icao"] = parts[idx]
            idx += 1
        
        if idx < len(parts) and parts[idx].endswith("Z"):
            result["time"] = parts[idx]
            idx += 1
        
        if idx < len(parts):
            wind_match = re.match(r"(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT", parts[idx])
            if wind_match:
                result["wind_dir"] = wind_match.group(1)
                result["wind_speed"] = int(wind_match.group(2))
                if wind_match.group(4):
                    result["wind_gust"] = int(wind_match.group(4))
                idx += 1
        
        if idx < len(parts) and re.match(r"\d{3}V\d{3}", parts[idx]):
            idx += 1
        
        if idx < len(parts):
            if parts[idx] == "CAVOK":
                result["visibility_m"] = 10000
                result["visibility_str"] = "CAVOK (>10km)"
                idx += 1
            elif parts[idx] == "9999":
                result["visibility_m"] = 10000
                result["visibility_str"] = ">10km"
                idx += 1
            elif re.match(r"\d{4}", parts[idx]):
                result["visibility_m"] = int(parts[idx])
                result["visibility_str"] = f"{int(parts[idx])}m"
                idx += 1
        
        while idx < len(parts):
            part = parts[idx]
            if part in WEATHER_PHENOMENA or any(part.startswith(p) for p in ["+", "-"]):
                result["weather"].append(part)
                result["weather_decoded"].append(WEATHER_PHENOMENA.get(part, part))
                idx += 1
            else:
                break
        
        cloud_prefixes = ["FEW", "SCT", "BKN", "OVC", "CLR", "SKC", "NSC", "VV"]
        while idx < len(parts):
            part = parts[idx]
            if any(part.startswith(cp) for cp in cloud_prefixes):
                result["clouds"].append(part)
                height_match = re.search(r"(\d{3})", part)
                height_ft = int(height_match.group(1)) * 100 if height_match else None
                cloud_type = part[:3]
                cloud_name = CLOUD_TYPES.get(cloud_type, cloud_type)
                if height_ft:
                    result["clouds_decoded"].append(f"{cloud_name} a {height_ft}ft")
                    if cloud_type in ["BKN", "OVC", "VV"] and result["ceiling_ft"] is None:
                        result["ceiling_ft"] = height_ft
                idx += 1
            else:
                break
        
        for part in parts[idx:]:
            temp_match = re.match(r"(M?\d{2})/(M?\d{2})", part)
            if temp_match:
                result["temperature"] = int(temp_match.group(1).replace("M", "-"))
                result["dewpoint"] = int(temp_match.group(2).replace("M", "-"))
            if part.startswith("Q") and len(part) == 5:
                result["pressure"] = int(part[1:])
        
        result["flight_category"] = self._determine_flight_category(result)
        result["is_ifr_closed"], result["closure_reasons"] = self._check_ifr_closure(result)
        
        return result
    
    def _determine_flight_category(self, metar: Dict) -> str:
        """
        Determina categoria de voo baseado em visibilidade e teto
        Inclui categoria HELI_CLOSED para operacoes de helicoptero
        """
        ceiling = metar.get("ceiling_ft")
        vis_m = metar.get("visibility_m", 10000)
        vis_sm = vis_m / 1609.34
        
        if ceiling is not None and ceiling < HELI_MINIMUMS["ceiling_ft"]:
            if ceiling < 500 or vis_sm < 1:
                return "LIFR"
        if vis_m < HELI_MINIMUMS["visibility_m"]:
            if vis_sm < 1:
                return "LIFR"
        
        if (ceiling is not None and ceiling < 500) or vis_sm < 1:
            return "LIFR"
        elif (ceiling is not None and ceiling < 1000) or vis_sm < 3:
            return "IFR"
        elif (ceiling is not None and ceiling < 3000) or vis_sm < 5:
            return "MVFR"
        else:
            return "VFR"
    
    def _check_heli_closed(self, metar: Dict) -> Tuple[bool, List[str]]:
        """Verifica se condicoes fecham operacoes de helicoptero"""
        reasons = []
        ceiling = metar.get("ceiling_ft")
        vis_m = metar.get("visibility_m", 10000)
        
        if ceiling is not None and ceiling < HELI_MINIMUMS["ceiling_ft"]:
            reasons.append(f"Teto abaixo do minimo HELI ({ceiling}ft < {HELI_MINIMUMS['ceiling_ft']}ft)")
        
        if vis_m < HELI_MINIMUMS["visibility_m"]:
            reasons.append(f"Visibilidade abaixo do minimo HELI ({vis_m}m < {HELI_MINIMUMS['visibility_m']}m)")
        
        return len(reasons) > 0, reasons
    
    def _check_ifr_closure(self, metar: Dict) -> Tuple[bool, List[str]]:
        """Verifica se condicoes indicam fechamento para IFR ou helicoptero"""
        reasons = []
        ceiling = metar.get("ceiling_ft")
        vis_m = metar.get("visibility_m", 10000)
        weather = metar.get("weather", [])
        
        heli_closed, heli_reasons = self._check_heli_closed(metar)
        if heli_closed:
            reasons.extend(heli_reasons)
        
        if ceiling is not None and ceiling < 200:
            reasons.append(f"Teto muito baixo ({ceiling}ft < 200ft)")
        
        if vis_m < 550:
            reasons.append(f"Visibilidade muito baixa ({vis_m}m < 550m)")
        
        for wx in weather:
            if "TS" in wx:
                reasons.append(f"Trovoadas ativas ({wx})")
            if wx == "FG" or (wx.endswith("FG") and not wx.startswith("BC") and not wx.startswith("MI")):
                reasons.append(f"Nevoeiro ({wx})")
        
        if any("CB" in c for c in metar.get("clouds", [])):
            reasons.append("Cumulonimbus presente")
        
        wind_gust = metar.get("wind_gust")
        if wind_gust and wind_gust > 35:
            reasons.append(f"Rajadas fortes ({wind_gust}kt > 35kt)")
        
        return len(reasons) > 0, reasons
    
    def parse_noaa_taf(self, noaa_data: Dict) -> Dict:
        """Converte TAF JSON do NOAA para formato interno"""
        raw = noaa_data.get("rawTAF", "")
        icao = noaa_data.get("icaoId", "")
        
        result = {
            "raw": raw,
            "icao": icao,
            "issue_time": noaa_data.get("issueTime"),
            "valid_from": noaa_data.get("validTimeFrom"),
            "valid_to": noaa_data.get("validTimeTo"),
            "periods": [],
            "fcsts": noaa_data.get("fcsts", []),
            "has_ifr_forecast": False,
            "ifr_periods": [],
            "worst_period": None
        }
        
        fcsts = noaa_data.get("fcsts", [])
        worst_conditions = {"ceiling": 99999, "vis": 99999, "period_desc": None}
        
        for fcst in fcsts:
            visib_raw = fcst.get("visib", "6+")
            if visib_raw == "6+":
                vis_m = 10000
            elif isinstance(visib_raw, (int, float)):
                vis_m = int(visib_raw * 1609.34)
            else:
                vis_m = 10000
            
            clouds_raw = fcst.get("clouds", [])
            ceiling_ft = None
            for cloud in clouds_raw:
                cover = cloud.get("cover", "")
                base = cloud.get("base")
                if cover in ["BKN", "OVC", "VV"] and base and ceiling_ft is None:
                    ceiling_ft = base
            
            wx_string = fcst.get("wxString", "")
            change_type = fcst.get("fcstChange") or "BASE"
            prob = fcst.get("probability")
            
            is_ifr = False
            reasons = []
            
            if ceiling_ft and ceiling_ft < 1000:
                is_ifr = True
                reasons.append(f"Teto {ceiling_ft}ft")
            if vis_m < 5000:
                is_ifr = True
                reasons.append(f"Vis {vis_m}m")
            if wx_string and any(x in wx_string for x in ["TS", "FG", "+RA"]):
                is_ifr = True
                reasons.append(f"Tempo: {wx_string}")
            
            period = {
                "type": change_type,
                "probability": prob,
                "visibility_m": vis_m,
                "ceiling_ft": ceiling_ft,
                "weather": wx_string,
                "is_ifr": is_ifr,
                "reasons": reasons,
            }
            
            result["periods"].append(period)
            
            if is_ifr:
                result["has_ifr_forecast"] = True
                
                time_from = fcst.get("timeFrom")
                time_to = fcst.get("timeTo")
                
                if time_from:
                    try:
                        dt_from = datetime.fromtimestamp(time_from, tz=timezone.utc)
                        dt_from_local = dt_from.replace(tzinfo=None) - timedelta(hours=3)
                        hora_inicio = dt_from_local.strftime("%H:%M")
                    except:
                        hora_inicio = "?"
                else:
                    hora_inicio = "?"
                
                if time_to:
                    try:
                        dt_to = datetime.fromtimestamp(time_to, tz=timezone.utc)
                        dt_to_local = dt_to.replace(tzinfo=None) - timedelta(hours=3)
                        hora_fim = dt_to_local.strftime("%H:%M")
                    except:
                        hora_fim = "?"
                else:
                    hora_fim = "?"
                
                periodo_horario = f"{hora_inicio}-{hora_fim}" if hora_inicio != "?" else change_type
                
                if prob:
                    prob_desc = f"{prob}% chance de "
                    if "TS" in wx_string:
                        prob_desc += "trovoada"
                    elif "RA" in wx_string:
                        prob_desc += "chuva forte"
                    elif "FG" in wx_string:
                        prob_desc += "nevoeiro"
                    else:
                        prob_desc += "IFR"
                    
                    ifr_desc = f"{periodo_horario}: {prob_desc} ({', '.join(reasons)})"
                else:
                    change_desc = {
                        "BASE": "Condicao base",
                        "BECMG": "Mudando para",
                        "TEMPO": "Temporariamente",
                        "FM": "A partir de"
                    }.get(change_type, change_type)
                    
                    ifr_desc = f"{periodo_horario}: {change_desc} - {', '.join(reasons)}"
                
                result["ifr_periods"].append(ifr_desc)
                
                effective_ceiling = ceiling_ft or 99999
                effective_vis = vis_m
                if prob and prob < 40:
                    pass
                elif effective_ceiling < worst_conditions["ceiling"] or effective_vis < worst_conditions["vis"]:
                    worst_conditions["ceiling"] = effective_ceiling
                    worst_conditions["vis"] = effective_vis
                    worst_conditions["period_desc"] = f"{periodo_horario}: {', '.join(reasons)}"
        
        if worst_conditions["period_desc"]:
            result["worst_period"] = worst_conditions["period_desc"]
        
        return result
    
    def parse_taf(self, taf_text: str) -> Dict:
        """Parse basico de TAF"""
        result = {
            "raw": taf_text,
            "icao": None,
            "issue_time": None,
            "valid_from": None,
            "valid_to": None,
            "periods": [],
            "has_ifr_forecast": False,
            "ifr_periods": []
        }
        
        lines = taf_text.replace("\n", " ").strip()
        parts = lines.split()
        
        if not parts:
            return result
        
        idx = 0
        if parts[idx] == "TAF":
            idx += 1
        if idx < len(parts) and parts[idx] == "AMD":
            idx += 1
        
        if idx < len(parts) and len(parts[idx]) == 4:
            result["icao"] = parts[idx]
            idx += 1
        
        if idx < len(parts) and parts[idx].endswith("Z"):
            result["issue_time"] = parts[idx]
            idx += 1
        
        if idx < len(parts):
            validity_match = re.match(r"(\d{4})/(\d{4})", parts[idx])
            if validity_match:
                result["valid_from"] = validity_match.group(1)
                result["valid_to"] = validity_match.group(2)
                idx += 1
        
        current_period = {"type": "BASE", "conditions": [], "raw": ""}
        
        while idx < len(parts):
            part = parts[idx]
            
            if part.startswith("TEMPO") or part.startswith("BECMG") or part.startswith("PROB"):
                if current_period["raw"]:
                    result["periods"].append(current_period)
                
                period_type = part
                if part.startswith("PROB"):
                    period_type = f"{part} {parts[idx+1]}" if idx+1 < len(parts) else part
                    idx += 1
                
                current_period = {"type": period_type, "conditions": [], "raw": ""}
            elif re.match(r"\d{4}/\d{4}", part):
                current_period["time_range"] = part
            
            current_period["raw"] += part + " "
            
            if part == "9999" or (re.match(r"\d{4}", part) and len(part) == 4 and not part.endswith("Z")):
                try:
                    vis = int(part)
                    if vis < 5000:
                        current_period["conditions"].append(f"Visibilidade {vis}m")
                        if vis < 1600:
                            result["has_ifr_forecast"] = True
                            result["ifr_periods"].append(f"{current_period['type']}: Vis {vis}m")
                except ValueError:
                    pass
            
            for code in ["FG", "BR", "TS", "TSRA", "+RA", "SN"]:
                if code in part:
                    current_period["conditions"].append(WEATHER_PHENOMENA.get(part, part))
                    if code in ["FG", "TS", "TSRA"]:
                        result["has_ifr_forecast"] = True
                        result["ifr_periods"].append(f"{current_period['type']}: {part}")
            
            if any(part.startswith(ct) for ct in ["BKN", "OVC", "VV"]):
                height_match = re.search(r"(\d{3})", part)
                if height_match:
                    height = int(height_match.group(1)) * 100
                    current_period["conditions"].append(f"Teto {height}ft")
                    if height < 1000:
                        result["has_ifr_forecast"] = True
                        result["ifr_periods"].append(f"{current_period['type']}: Teto {height}ft")
            
            idx += 1
        
        if current_period["raw"]:
            result["periods"].append(current_period)
        
        return result
    
    def load_state(self) -> Dict:
        """Carrega estado anterior"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Erro ao carregar estado: {e}")
        return {'last_metars': {}, 'last_tafs': {}, 'last_alerts': [], 'last_check': None}
    
    def save_state(self, state: Dict):
        """Salva estado atual"""
        try:
            state['last_check'] = datetime.now().isoformat()
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Erro ao salvar estado: {e}")
    
    def check_weather(self) -> Dict:
        """Verifica condicoes meteorologicas e retorna alertas"""
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metars": [],
            "tafs": [],
            "alerts": [],
            "has_critical_alert": False
        }
        
        try:
            noaa_metars = self.fetch_metars_json()
            for noaa_data in noaa_metars:
                parsed = self.parse_noaa_metar(noaa_data)
                result["metars"].append(parsed)
                
                if parsed["is_ifr_closed"]:
                    airport = AIRPORT_INFO.get(parsed["icao"], {})
                    alert = {
                        "type": parsed["type"],
                        "icao": parsed["icao"],
                        "airport_name": airport.get("name", parsed["icao"]),
                        "category": parsed["flight_category"],
                        "reasons": parsed["closure_reasons"],
                        "raw": parsed["raw"]
                    }
                    result["alerts"].append(alert)
                    result["has_critical_alert"] = True
        except Exception as e:
            logging.error(f"Erro ao buscar METARs JSON do NOAA: {e}")
            try:
                raw_metars = self.fetch_metars()
                for line in raw_metars.strip().split("\n"):
                    if line.strip():
                        parsed = self.parse_metar(line.strip())
                        result["metars"].append(parsed)
                        
                        if parsed["is_ifr_closed"]:
                            airport = AIRPORT_INFO.get(parsed["icao"], {})
                            alert = {
                                "type": parsed["type"],
                                "icao": parsed["icao"],
                                "airport_name": airport.get("name", parsed["icao"]),
                                "category": parsed["flight_category"],
                                "reasons": parsed["closure_reasons"],
                                "raw": parsed["raw"]
                            }
                            result["alerts"].append(alert)
                            result["has_critical_alert"] = True
            except Exception as e2:
                logging.error(f"Erro ao buscar METARs raw: {e2}")
        
        try:
            noaa_tafs = self.fetch_tafs_json()
            for noaa_data in noaa_tafs:
                parsed = self.parse_noaa_taf(noaa_data)
                result["tafs"].append(parsed)
                
                if parsed["has_ifr_forecast"]:
                    airport = AIRPORT_INFO.get(parsed["icao"], {})
                    alert = {
                        "type": "TAF",
                        "icao": parsed["icao"],
                        "airport_name": airport.get("name", parsed["icao"]),
                        "category": "IFR PREVISTO",
                        "reasons": parsed["ifr_periods"],
                        "ifr_periods": parsed["ifr_periods"],
                        "worst_period": parsed.get("worst_period"),
                        "raw": parsed["raw"][:200] + "..."
                    }
                    result["alerts"].append(alert)
        except Exception as e:
            logging.error(f"Erro ao buscar TAFs JSON do NOAA: {e}")
            try:
                raw_tafs = self.fetch_tafs()
                current_taf = ""
                
                for line in raw_tafs.strip().split("\n"):
                    if line.strip().startswith("TAF") and current_taf:
                        parsed = self.parse_taf(current_taf)
                        result["tafs"].append(parsed)
                        
                        if parsed["has_ifr_forecast"]:
                            airport = AIRPORT_INFO.get(parsed["icao"], {})
                            alert = {
                                "type": "TAF",
                                "icao": parsed["icao"],
                                "airport_name": airport.get("name", parsed["icao"]),
                                "category": "IFR PREVISTO",
                                "reasons": parsed["ifr_periods"],
                                "ifr_periods": parsed["ifr_periods"],
                                "worst_period": parsed.get("worst_period"),
                                "raw": parsed["raw"][:200] + "..."
                            }
                            result["alerts"].append(alert)
                        
                        current_taf = line.strip()
                    else:
                        current_taf += " " + line.strip()
                
                if current_taf:
                    parsed = self.parse_taf(current_taf)
                    result["tafs"].append(parsed)
                    if parsed["has_ifr_forecast"]:
                        airport = AIRPORT_INFO.get(parsed["icao"], {})
                        alert = {
                            "type": "TAF",
                            "icao": parsed["icao"],
                            "airport_name": airport.get("name", parsed["icao"]),
                            "category": "IFR PREVISTO",
                            "reasons": parsed["ifr_periods"],
                            "ifr_periods": parsed["ifr_periods"],
                            "worst_period": parsed.get("worst_period"),
                            "raw": parsed["raw"][:200] + "..."
                        }
                        result["alerts"].append(alert)
            except Exception as e2:
                logging.error(f"Erro ao buscar TAFs raw: {e2}")
        
        return result
    
    def has_speci(self, weather_data: Dict) -> List[Dict]:
        """Verifica se ha SPECIs nos dados meteorologicos"""
        specis = []
        for metar in weather_data.get("metars", []):
            if metar.get("type") == "SPECI":
                specis.append(metar)
        return specis
    
    def get_weather_images_for_speci(self) -> Dict:
        """Busca imagens meteorologicas para acompanhar SPECI (usa fontes gratuitas)"""
        try:
            from weather_images import WeatherImagesClient
            client = WeatherImagesClient()
            return client.get_speci_package()
        except ImportError:
            logging.warning("Modulo weather_images nao disponivel")
            return {}
        except Exception as e:
            logging.error(f"Erro ao buscar imagens: {e}")
            return {}
    
    def format_metar_decoded(self, metar: Dict) -> str:
        """Formata METAR decodificado para exibicao"""
        icao = metar.get("icao", "????")
        airport = AIRPORT_INFO.get(icao, {})
        name = airport.get("name", icao)
        
        lines = [f"<b>{icao} - {name}</b>"]
        lines.append(f"<code>{metar.get('raw', '')}</code>")
        lines.append("")
        
        cat = metar.get("flight_category", "N/A")
        cat_emoji = {"VFR": "🟢", "MVFR": "🔵", "IFR": "🔴", "LIFR": "🟣"}.get(cat, "⚪")
        lines.append(f"Categoria: {cat_emoji} <b>{cat}</b>")
        
        if metar.get("wind_speed") is not None:
            wind = f"{metar.get('wind_dir', 'VRB')}° / {metar['wind_speed']}kt"
            if metar.get("wind_gust"):
                wind += f" (rajadas {metar['wind_gust']}kt)"
            lines.append(f"Vento: {wind}")
        
        if metar.get("visibility_str"):
            lines.append(f"Visibilidade: {metar['visibility_str']}")
        
        if metar.get("ceiling_ft"):
            lines.append(f"Teto: {metar['ceiling_ft']}ft")
        
        if metar.get("clouds_decoded"):
            lines.append(f"Nuvens: {', '.join(metar['clouds_decoded'])}")
        
        if metar.get("weather_decoded"):
            lines.append(f"Tempo: {', '.join(metar['weather_decoded'])}")
        
        if metar.get("temperature") is not None:
            lines.append(f"Temperatura: {metar['temperature']}C / Orvalho: {metar.get('dewpoint', 'N/A')}C")
        
        if metar.get("pressure"):
            lines.append(f"Pressao: {metar['pressure']} hPa")
        
        return "\n".join(lines)
    
    def format_taf_summary(self, taf: Dict) -> str:
        """Formata resumo do TAF"""
        icao = taf.get("icao", "????")
        airport = AIRPORT_INFO.get(icao, {})
        name = airport.get("name", icao)
        
        lines = [f"<b>{icao} - {name} (TAF)</b>"]
        
        if taf.get("valid_from") and taf.get("valid_to"):
            lines.append(f"Validade: {taf['valid_from']} a {taf['valid_to']} UTC")
        
        if taf.get("has_ifr_forecast"):
            lines.append("⚠️ <b>PREVISAO DE IFR:</b>")
            for period in taf.get("ifr_periods", []):
                lines.append(f"  - {period}")
        else:
            lines.append("✅ Sem previsao de IFR significativo")
        
        return "\n".join(lines)
    
    def format_sigmet_message(self, sigmet: Dict) -> str:
        """Formata SIGMET para exibicao"""
        parsed = self.parse_sigmet(sigmet)
        
        hazard_emoji = {
            "TS": "⛈️",
            "TURB": "🌀",
            "ICE": "🧊",
            "TC": "🌀",
            "VA": "🌋",
        }
        
        emoji = hazard_emoji.get(parsed["hazard"], "⚠️")
        
        lines = []
        lines.append(f"{emoji} <b>SIGMET {parsed['fir']}</b>")
        lines.append(f"  {parsed['qualifier_text']} {parsed['hazard_text']}")
        if parsed["level"]:
            lines.append(f"  Nivel: {parsed['level']}")
        
        return "\n".join(lines)
    
    def format_sigmets_summary(self, sigmets: List[Dict]) -> str:
        """Formata resumo de SIGMETs ativos"""
        if not sigmets:
            return ""
        
        lines = ["<b>SIGMET ATIVOS - BRASIL</b>"]
        
        ts_sigmets = [s for s in sigmets if s.get('hazard') == 'TS']
        turb_sigmets = [s for s in sigmets if s.get('hazard') == 'TURB']
        ice_sigmets = [s for s in sigmets if s.get('hazard') == 'ICE']
        other_sigmets = [s for s in sigmets if s.get('hazard') not in ['TS', 'TURB', 'ICE']]
        
        if ts_sigmets:
            lines.append(f"⛈️ Tempestades: {len(ts_sigmets)} SIGMET(s)")
        if turb_sigmets:
            lines.append(f"🌀 Turbulencia: {len(turb_sigmets)} SIGMET(s)")
        if ice_sigmets:
            lines.append(f"🧊 Gelo: {len(ice_sigmets)} SIGMET(s)")
        if other_sigmets:
            lines.append(f"⚠️ Outros: {len(other_sigmets)} SIGMET(s)")
        
        lines.append("")
        for sigmet in sigmets[:5]:
            lines.append(self.format_sigmet_message(sigmet))
        
        if len(sigmets) > 5:
            lines.append(f"... e mais {len(sigmets) - 5} SIGMET(s)")
        
        return "\n".join(lines)
    
    def format_weather_alert(self, alert: Dict) -> str:
        """Formata mensagem de alerta meteorologico (METAR/TAF)"""
        icao = alert.get("icao", "????")
        name = alert.get("airport_name", icao)
        alert_type = alert.get("type", "METAR")
        category = alert.get("category", "N/A")
        
        if alert_type in ["METAR", "SPECI"]:
            emoji = "🔴" if category in ["IFR", "LIFR"] else "⚠️"
            title = f"{emoji} <b>ALERTA METEO - {icao} ({name})</b>"
        else:
            emoji = "⚠️"
            title = f"{emoji} <b>PREVISAO IFR - {icao} ({name})</b>"
        
        lines = [title, ""]
        lines.append(f"<b>Tipo:</b> {alert_type}")
        lines.append(f"<b>Categoria:</b> {category}")
        lines.append("")
        lines.append("<b>Motivos:</b>")
        for reason in alert.get("reasons", []):
            lines.append(f"  • {reason}")
        
        lines.append("")
        lines.append(f"<code>{alert.get('raw', '')}</code>")
        
        return "\n".join(lines)
    
    def format_weather_summary(self, weather_data: Dict) -> str:
        """Formata resumo meteorologico completo"""
        lines = ["<b>METEOROLOGIA SP - AEROPORTOS</b>"]
        lines.append(f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')} (local)")
        lines.append("")
        
        for metar in weather_data.get("metars", []):
            lines.append(self.format_metar_decoded(metar))
            lines.append("")
        
        sigmets = weather_data.get("sigmets", [])
        if sigmets:
            lines.append(self.format_sigmets_summary(sigmets))
            lines.append("")
        
        lines.append("<b>PREVISOES (TAF)</b>")
        lines.append("")
        
        for taf in weather_data.get("tafs", []):
            lines.append(self.format_taf_summary(taf))
            lines.append("")
        
        return "\n".join(lines)
    
    def get_full_weather_data(self) -> Dict:
        """Coleta todos os dados meteorologicos incluindo SIGMETs"""
        result = {
            "metars": [],
            "tafs": [],
            "sigmets": [],
            "alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            metars_json = self.fetch_metars_json()
            for noaa_metar in metars_json:
                parsed = self.parse_noaa_metar(noaa_metar)
                result["metars"].append(parsed)
        except Exception as e:
            logging.error(f"Erro ao buscar METARs: {e}")
        
        try:
            tafs_json = self.fetch_tafs_json()
            for noaa_taf in tafs_json:
                parsed = self.parse_noaa_taf(noaa_taf)
                result["tafs"].append(parsed)
        except Exception as e:
            logging.error(f"Erro ao buscar TAFs: {e}")
        
        try:
            result["sigmets"] = self.fetch_sigmets_brazil()
            logging.info(f"SIGMETs Brasil: {len(result['sigmets'])} ativos")
        except Exception as e:
            logging.error(f"Erro ao buscar SIGMETs: {e}")
        
        return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor Meteorologico - REVO')
    parser.add_argument('--check', action='store_true', help='Verifica condicoes atuais')
    parser.add_argument('--alerts-only', action='store_true', help='Mostra apenas alertas')
    parser.add_argument('--sigmets', action='store_true', help='Mostra SIGMETs Brasil')
    parser.add_argument('--full', action='store_true', help='Dados completos (METAR+TAF+SIGMET)')
    parser.add_argument('--json', action='store_true', help='Saida em JSON')
    
    args = parser.parse_args()
    
    monitor = WeatherMonitor()
    
    if args.sigmets:
        print("=" * 60)
        print("SIGMET ATIVOS - BRASIL")
        print("=" * 60)
        sigmets = monitor.fetch_sigmets_brazil()
        print(f"Total: {len(sigmets)} SIGMET(s)")
        
        for sigmet in sigmets:
            parsed = monitor.parse_sigmet(sigmet)
            print(f"\n{parsed['fir']} - {parsed['fir_name']}")
            print(f"  Tipo: {parsed['qualifier_text']} {parsed['hazard_text']}")
            if parsed['level']:
                print(f"  Nivel: {parsed['level']}")
            print(f"  Raw: {parsed['raw'][:100]}...")
        return
    
    if args.full:
        weather = monitor.get_full_weather_data()
        if args.json:
            print(json.dumps(weather, indent=2, ensure_ascii=False, default=str))
        else:
            print(monitor.format_weather_summary(weather).replace("<b>", "**").replace("</b>", "**").replace("<code>", "").replace("</code>", ""))
        return
    
    if args.check or not any([args.alerts_only, args.sigmets, args.full]):
        weather = monitor.check_weather()
        
        if args.json:
            print(json.dumps(weather, indent=2, ensure_ascii=False))
        elif args.alerts_only:
            if weather["alerts"]:
                print("=" * 60)
                print("ALERTAS METEOROLOGICOS")
                print("=" * 60)
                for alert in weather["alerts"]:
                    print(monitor.format_weather_alert(alert).replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                    print("-" * 60)
            else:
                print("Nenhum alerta meteorologico no momento")
        else:
            print("=" * 60)
            print("METEOROLOGIA - AEROPORTOS DE SAO PAULO")
            print(f"Atualizado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
            print("=" * 60)
            
            for metar in weather["metars"]:
                icao = metar.get("icao", "????")
                airport = AIRPORT_INFO.get(icao, {})
                name = airport.get("name", icao)
                cat = metar.get("flight_category", "N/A")
                
                print(f"\n{icao} - {name}")
                print(f"  Raw: {metar.get('raw', '')}")
                print(f"  Categoria: {cat}")
                if metar.get("visibility_str"):
                    print(f"  Visibilidade: {metar['visibility_str']}")
                if metar.get("ceiling_ft"):
                    print(f"  Teto: {metar['ceiling_ft']}ft")
                if metar.get("weather_decoded"):
                    print(f"  Tempo: {', '.join(metar['weather_decoded'])}")
                if metar.get("is_ifr_closed"):
                    print(f"  ⚠️  RESTRICOES: {', '.join(metar['closure_reasons'])}")
            
            print("\n" + "=" * 60)
            print("PREVISOES (TAF)")
            print("=" * 60)
            
            for taf in weather["tafs"]:
                icao = taf.get("icao", "????")
                airport = AIRPORT_INFO.get(icao, {})
                name = airport.get("name", icao)
                
                print(f"\n{icao} - {name}")
                if taf.get("has_ifr_forecast"):
                    print("  ⚠️  PREVISAO DE IFR:")
                    for period in taf.get("ifr_periods", []):
                        print(f"    - {period}")
                else:
                    print("  ✓ Sem previsao de IFR significativo")
            
            if weather["alerts"]:
                print("\n" + "=" * 60)
                print("⚠️  ALERTAS ATIVOS")
                print("=" * 60)
                for alert in weather["alerts"]:
                    print(f"\n{alert['icao']} - {alert['airport_name']}: {alert['category']}")
                    for reason in alert.get("reasons", []):
                        print(f"  - {reason}")


if __name__ == "__main__":
    main()
