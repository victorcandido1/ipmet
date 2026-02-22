"""
Módulo de Notificações via Telegram - REVO
Envia alertas sobre novos voos, cancelamentos, resumo diário e custos operacionais
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import logging
import plotly.express as px
import plotly.graph_objects as go
from utils import format_currency as utils_format_currency

try:
    from empty_legs_calculator import EmptyLegCalculator, CostCalculator, PTAXFetcher
    CUSTOS_AVAILABLE = True
except ImportError:
    CUSTOS_AVAILABLE = False

try:
    from adsb_tracker import ADSBTracker, FROTA_HELICOPTEROS
    ADSB_AVAILABLE = True
except ImportError:
    ADSB_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_notifications.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

load_dotenv()

# Coordenadas dos helipontos
HELIPONTOS = {
    'SBGR': {'nome': 'Aeroporto Guarulhos', 'lat': -23.4356, 'lon': -46.4731},
    'SIIR': {'nome': 'Brascan Century Plaza', 'lat': -23.5867, 'lon': -46.6803},
    'SDMN': {'nome': 'Continental Tower', 'lat': -23.5922, 'lon': -46.6947},
    'SDOF': {'nome': 'Ed. Paladio', 'lat': -23.5958, 'lon': -46.6856},
    'SDXQ': {'nome': 'Faria Lima Plaza II', 'lat': -23.5747, 'lon': -46.6894},
    'SIJF': {'nome': 'Faria Lima Financial', 'lat': -23.5761, 'lon': -46.6889},
    'SDCY': {'nome': 'Corporate Tower', 'lat': -23.5969, 'lon': -46.6919},
    'SDBR': {'nome': 'Vivo REC Berrini', 'lat': -23.6028, 'lon': -46.6964},
    'SNGL': {'nome': 'Fazenda Boa Vista', 'lat': -23.2667, 'lon': -47.4833},
    'SSJN': {'nome': 'Faz. Santa Helena', 'lat': -22.9517, 'lon': -46.5419},
    'SDLA': {'nome': 'Cond. Laranjeiras', 'lat': -23.2167, 'lon': -44.7167},
    'SJCG': {'nome': 'Iate Clube Angra', 'lat': -23.0067, 'lon': -44.3183},
    'SDKR': {'nome': 'Faz. Santo Antonio', 'lat': -22.3572, 'lon': -47.3847},
    'SDQY': {'nome': 'Iguatemi Campinas', 'lat': -22.8267, 'lon': -47.0731},
    'SITP': {'nome': 'Clara Resort', 'lat': -23.6567, 'lon': -47.2231},
    'SBJH': {'nome': 'Catarina Aeroporto', 'lat': -23.4281, 'lon': -47.1653},
    'SDLF': {'nome': 'SBT', 'lat': -23.6328, 'lon': -46.7167},
    'SWWD': {'nome': 'Dom Pedro Atibaia', 'lat': -23.1167, 'lon': -46.5500},
    'SJWD': {'nome': 'Campos do Jordão', 'lat': -22.4167, 'lon': -45.4500},
    'SDRR': {'nome': 'Avaré-Arandu', 'lat': -23.0983, 'lon': -48.9253},
    'SNJ6': {'nome': 'Heliponto Nitzan', 'lat': -23.5500, 'lon': -46.6333},
    'SDFW': {'nome': 'San Paolo', 'lat': -23.5505, 'lon': -46.6333},
    'SNSZ': {'nome': 'Miss Silvia', 'lat': -23.5614, 'lon': -46.6558},
    'SD3I': {'nome': 'Raízen Piracicaba', 'lat': -22.7253, 'lon': -47.6492},
    'ZPFZ': {'nome': 'Porto Feliz Privado', 'lat': -23.2150, 'lon': -47.5250},
}

PREFIXOS_VALIDOS = {'PR-OMB', 'PR-OMH', 'PR-OOE'}


def _extrair_prefixo(voo):
    """Extrai o prefixo real da aeronave (PR-OMB, PR-OMH, PR-OOE) do registro Salesforce.

    Prioridade:
    1. Prefixo__r.Name  (relacionamento com Aeronave__c - mais confiavel)
    2. Voo_Prefixo      (campo processado pelo salesforce_extractor)
    3. PrefixoTexto__c  (campo texto - pode conter valores incorretos como PR-REV)
    4. Prefixo__c       (campo lookup - pode ser ID)
    """
    # 1. Relationship field (mais confiavel)
    prefixo_r = voo.get('Prefixo__r')
    if isinstance(prefixo_r, dict):
        name = prefixo_r.get('Name', '')
        if name:
            name = str(name).upper().strip()
            if name in PREFIXOS_VALIDOS:
                return name

    # 2. Campo processado pelo extractor
    voo_prefixo = voo.get('Voo_Prefixo', '')
    if voo_prefixo:
        voo_prefixo = str(voo_prefixo).upper().strip()
        if voo_prefixo in PREFIXOS_VALIDOS:
            return voo_prefixo

    # 3. PrefixoTexto__c (pode ser incorreto, validar contra lista)
    texto = voo.get('PrefixoTexto__c', '')
    if texto:
        texto = str(texto).upper().strip()
        if texto in PREFIXOS_VALIDOS:
            return texto

    # 4. Prefixo__c (lookup - geralmente e um ID, mas tentar)
    lookup = voo.get('Prefixo__c', '')
    if lookup:
        lookup = str(lookup).upper().strip()
        if lookup in PREFIXOS_VALIDOS:
            return lookup

    # Fallback: retorna o melhor candidato encontrado (sem validacao)
    for field in ('Prefixo__r', 'Voo_Prefixo', 'PrefixoTexto__c', 'Prefixo__c'):
        val = voo.get(field)
        if isinstance(val, dict):
            val = val.get('Name', '')
        if val and str(val).strip() and not str(val).startswith('a0'):
            return str(val).strip()

    return '-'


class TelegramNotifier:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        from state_manager import get_state_manager
        self._state_manager = get_state_manager()
        self.state_file = self._state_manager.telegram_state_file
        self.last_update_id = 0
    
    def is_configured(self):
        """Verifica se as credenciais do Telegram estão configuradas"""
        if not self.bot_token or not self.chat_id:
            logging.warning("Telegram não configurado. Adicione TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env")
            return False
        return True
    
    def get_updates(self, offset=None):
        """Busca novas mensagens do Telegram"""
        if not self.is_configured():
            return []
        
        try:
            url = f"{self.base_url}/getUpdates"
            params = {'timeout': 5}
            if offset:
                params['offset'] = offset
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    return data.get('result', [])
            return []
        except Exception as e:
            logging.error(f"Erro ao buscar updates: {e}")
            return []
    
    def process_commands(self):
        """Processa comandos recebidos no Telegram"""
        updates = self.get_updates(offset=self.last_update_id + 1)
        
        for update in updates:
            self.last_update_id = update.get('update_id', 0)
            
            message = update.get('message', {})
            text = message.get('text', '').strip().upper()
            chat_id = message.get('chat', {}).get('id')
            
            if not text or str(chat_id) != str(self.chat_id):
                continue
            
            logging.info(f"Comando recebido: {text}")
            
            if text in ['METEOROLOGIA', 'METEO', 'TEMPO', '/METEOROLOGIA', '/METEO']:
                self.send_meteorologia_completa()
            elif text in ['BRIEFING', '/BRIEFING']:
                self.send_briefing_on_demand()
            elif text in ['VOOS', '/VOOS']:
                self.send_voos_on_demand()
            elif text in ['CAMERAS', 'WEBCAM', 'WEBCAMS', 'AO VIVO', '/CAMERAS', '/WEBCAM']:
                self.send_cameras_ao_vivo()
            elif text in ['FROTA', 'RASTREAMENTO', 'ADSB', 'POSICAO', '/FROTA', '/RASTREAMENTO', '/ADSB']:
                self.send_fleet_status()
            elif text in ['AJUDA', 'HELP', '/AJUDA', '/HELP']:
                self.send_help_message()
    
    def send_cameras_ao_vivo(self):
        """Envia links das cameras ao vivo"""
        live_links = """
<b>Cameras ao Vivo - Clique para abrir:</b>

<a href="https://www.youtube.com/watch?v=VkP9X7iz9Q">SBGR - Guarulhos (YouTube)</a>
Aeroporto Internacional de Guarulhos

<a href="https://www.youtube.com/watch?v=U3zQ1MQOiEg">SBSP - Congonhas (YouTube)</a>
Aeroporto de Congonhas

<a href="https://player.radiosnaweb.com/camera/helipark-sul">Helipark Sul</a>
Heliponto Helipark
"""
        self.send_message(live_links)
        logging.info("Links de cameras ao vivo enviados")
    
    def send_help_message(self):
        """Envia mensagem de ajuda com comandos disponiveis"""
        help_text = """
<b>Comandos Disponiveis:</b>

<b>METEOROLOGIA</b> - Pacote completo de imagens meteorologicas
<b>CAMERAS</b> - Links das webcams ao vivo
<b>BRIEFING</b> - Briefing completo (voos + meteo + mapas)
<b>VOOS</b> - Lista de voos de hoje e amanha
<b>FROTA</b> - Rastreamento ADS-B dos helicopteros
<b>AJUDA</b> - Mostra esta mensagem

<i>Os comandos podem ser enviados em maiusculas ou minusculas.</i>
"""
        self.send_message(help_text)
    
    def send_fleet_status(self):
        """Envia status de rastreamento ADS-B da frota"""
        if not ADSB_AVAILABLE:
            self.send_message("Modulo de rastreamento ADS-B nao disponivel.")
            return
        
        logging.info("Consultando rastreamento ADS-B da frota...")
        
        try:
            tracker = ADSBTracker()
            fleet_status = tracker.get_fleet_status()
            
            lines = [
                "<b>RASTREAMENTO ADS-B - FROTA REVO</b>",
                f"<i>Atualizado: {datetime.now().strftime('%H:%M:%S')}</i>",
                ""
            ]
            
            flying_count = 0
            
            for prefixo, state in fleet_status.items():
                heli_info = FROTA_HELICOPTEROS.get(prefixo, {})
                tipo = heli_info.get('tipo', 'Helicoptero')
                
                if state:
                    if state.get('on_ground'):
                        status_emoji = "🅿️"
                        status_text = "Em Solo"
                    else:
                        status_emoji = "✈️"
                        status_text = "EM VOO"
                        flying_count += 1
                    
                    lines.append(f"{status_emoji} <b>{prefixo}</b> ({tipo})")
                    lines.append(f"   Status: {status_text}")
                    
                    if not state.get('on_ground'):
                        if state.get('altitude_baro'):
                            alt_ft = round(state['altitude_baro'] * 3.281)
                            lines.append(f"   Altitude: {alt_ft} ft")
                        if state.get('velocity_kts'):
                            lines.append(f"   Velocidade: {state['velocity_kts']} kts")
                        if state.get('track') is not None:
                            direcoes = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
                            idx = int((state['track'] + 22.5) / 45) % 8
                            lines.append(f"   Proa: {round(state['track'])} ({direcoes[idx]})")
                        if state.get('latitude') and state.get('longitude'):
                            lines.append(f"   Posicao: {state['latitude']:.4f}, {state['longitude']:.4f}")
                    
                    if state.get('last_contact'):
                        lines.append(f"   Ultima detecao: {state['last_contact'].strftime('%H:%M:%S')}")
                else:
                    lines.append(f"❓ <b>{prefixo}</b> ({tipo})")
                    lines.append("   Nao detectado (em solo ou fora de cobertura ADS-B)")
                
                lines.append("")
            
            if flying_count > 0:
                lines.insert(3, f"<b>{flying_count} aeronave(s) em voo</b>")
                lines.insert(4, "")
            else:
                lines.insert(3, "<i>Nenhuma aeronave da frota em voo no momento</i>")
                lines.insert(4, "")
            
            lines.append("<i>Dados: OpenSky Network (ADS-B)</i>")
            
            self.send_message("\n".join(lines))
            logging.info(f"Status da frota enviado - {flying_count} em voo")
            
        except Exception as e:
            logging.error(f"Erro ao consultar rastreamento: {e}")
            self.send_message(f"Erro ao consultar rastreamento: {e}")
    
    def send_meteorologia_completa(self):
        """Envia pacote completo de imagens meteorologicas"""
        logging.info("Enviando meteorologia completa por comando...")
        
        try:
            from weather_images import WeatherImagesClient
            from weather_monitor import WeatherMonitor
            
            self.send_message("Gerando pacote meteorologico completo...")
            
            images_client = WeatherImagesClient()
            images = images_client.get_weather_update_package()
            
            weather_monitor = WeatherMonitor()
            weather_data = weather_monitor.check_weather()
            
            caption_base = f"Atualizacao Meteorologica - {datetime.now().strftime('%H:%M')}\n"
            
            has_alerts = any(m.get("is_ifr_closed") for m in weather_data.get("metars", []))
            if has_alerts:
                caption_base += "ALERTAS ATIVOS!\n"
            
            captions = {
                "radar_gif": f"{caption_base}Radar IPMET (GIF animado)",
                "satelite_gif": f"{caption_base}Satelite IPMET (GIF animado)",
                "sigwx": f"{caption_base}SIGWX Inferior (SUP-FL250)\nFenomenos significativos baixa altitude",
                "indice_k": f"{caption_base}Indice K - Potencial Tempestades\nK>30: Alta prob. | K>35: Severas",
                "ventos_850": f"{caption_base}Ventos 850 hPa (~1500m)\nAltitude cruzeiro helicopteros",
                "radar": f"{caption_base}Radar Meteorologico - SP",
                "satelite": f"{caption_base}Satelite GOES-16 (GEOCOLOR)",
                "nuvens": f"{caption_base}Infravermelho - Nuvens",
                "webcam_sbgr": f"{caption_base}Webcam SBGR - Guarulhos",
                "webcam_sbsp": f"{caption_base}Webcam SBSP - Congonhas",
                "webcam_helipark": f"{caption_base}Webcam Helipark",
            }
            
            sent_count = 0
            for name, path in images.items():
                if path and os.path.exists(path):
                    caption = captions.get(name, f"{caption_base}{name}")
                    
                    if path.endswith('.gif') and 'ipmet' in path.lower():
                        if self.send_animation(path, caption):
                            sent_count += 1
                    else:
                        if self.send_photo(path, caption):
                            sent_count += 1
            
            self.send_message(f"Pacote meteorologico enviado: {sent_count} imagens")
            
            live_links = """
<b>Cameras ao Vivo:</b>

<a href="https://www.youtube.com/watch?v=VkP9X7iz9Q">SBGR - Guarulhos (YouTube)</a>

<a href="https://www.youtube.com/watch?v=U3zQ1MQOiEg">SBSP - Congonhas (YouTube)</a>

<a href="https://player.radiosnaweb.com/camera/helipark-sul">Helipark Sul</a>
"""
            self.send_message(live_links)
            
            logging.info(f"Meteorologia completa enviada: {sent_count} imagens")
            
        except Exception as e:
            logging.error(f"Erro ao enviar meteorologia: {e}")
            self.send_message(f"Erro ao gerar meteorologia: {e}")
    
    def send_briefing_on_demand(self):
        """Envia briefing completo por demanda"""
        logging.info("Enviando briefing por comando...")
        
        try:
            from flight_monitor import FlightMonitor
            
            self.send_message("Gerando briefing completo...")
            
            monitor = FlightMonitor()
            monitor.send_morning_briefing()
            
        except Exception as e:
            logging.error(f"Erro ao enviar briefing: {e}")
            self.send_message(f"Erro ao gerar briefing: {e}")
    
    def send_voos_on_demand(self):
        """Envia lista de voos por demanda"""
        logging.info("Enviando voos por comando...")

        try:
            voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias = get_voos_salesforce()

            msg = f"<b>Voos de Hoje ({len(voos_hoje)}):</b>\n\n"

            for voo in voos_hoje:
                prefixo = voo.get('prefixo', 'N/A')
                origem = voo.get('origem', 'N/A')
                destino = voo.get('destino', 'N/A')
                hora = voo.get('hora', 'N/A')
                pax = voo.get('pax', 0)
                msg += f"{hora} {prefixo} | {origem}-{destino} | {pax}pax\n"

            if voos_amanha:
                msg += f"\n<b>Voos de Amanha ({len(voos_amanha)}):</b>\n\n"
                for voo in voos_amanha:
                    prefixo = voo.get('prefixo', 'N/A')
                    origem = voo.get('origem', 'N/A')
                    destino = voo.get('destino', 'N/A')
                    hora = voo.get('hora', 'N/A')
                    pax = voo.get('pax', 0)
                    msg += f"{hora} {prefixo} | {origem}-{destino} | {pax}pax\n"

            if voos_depois_amanha:
                depois_amanha_date = (datetime.now() + timedelta(days=2)).strftime('%d/%m')
                msg += f"\n<b>Depois de Amanha - {depois_amanha_date} ({len(voos_depois_amanha)}):</b>\n\n"
                for voo in voos_depois_amanha:
                    prefixo = voo.get('prefixo', 'N/A')
                    origem = voo.get('origem', 'N/A')
                    destino = voo.get('destino', 'N/A')
                    hora = voo.get('hora', 'N/A')
                    pax = voo.get('pax', 0)
                    msg += f"{hora} {prefixo} | {origem}-{destino} | {pax}pax\n"

            for dia_info in voos_proximos_dias:
                label = dia_info['label']
                dia_voos = dia_info['voos']
                msg += f"\n<b>{label} ({len(dia_voos)}):</b>\n\n"
                for voo in dia_voos:
                    prefixo = voo.get('prefixo', 'N/A')
                    origem = voo.get('origem', 'N/A')
                    destino = voo.get('destino', 'N/A')
                    hora = voo.get('hora', 'N/A')
                    pax = voo.get('pax', 0)
                    msg += f"{hora} {prefixo} | {origem}-{destino} | {pax}pax\n"

            self.send_message(msg)

        except Exception as e:
            logging.error(f"Erro ao enviar voos: {e}")
            self.send_message(f"Erro ao buscar voos: {e}")
    
    def send_message(self, message, parse_mode='HTML'):
        """Envia mensagem para o Telegram"""
        if not self.is_configured():
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logging.info("Mensagem enviada com sucesso")
                return True
            else:
                logging.error(f"Erro ao enviar mensagem: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem: {e}")
            return False
    
    def send_photo(self, image_path, caption=''):
        """Envia imagem para o Telegram"""
        if not self.is_configured():
            return False
        
        try:
            url = f"{self.base_url}/sendPhoto"
            with open(image_path, 'rb') as photo:
                payload = {
                    'chat_id': self.chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
                files = {'photo': photo}
                response = requests.post(url, data=payload, files=files, timeout=30)
            
            if response.status_code == 200:
                logging.info(f"Imagem enviada: {image_path}")
                return True
            else:
                logging.error(f"Erro ao enviar imagem: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Erro ao enviar imagem: {e}")
            return False
    
    def send_animation(self, gif_path, caption=''):
        """Envia GIF animado para o Telegram"""
        if not self.is_configured():
            return False
        
        try:
            url = f"{self.base_url}/sendAnimation"
            with open(gif_path, 'rb') as animation:
                payload = {
                    'chat_id': self.chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
                files = {'animation': animation}
                response = requests.post(url, data=payload, files=files, timeout=60)
            
            if response.status_code == 200:
                logging.info(f"GIF animado enviado: {gif_path}")
                return True
            else:
                logging.error(f"Erro ao enviar GIF: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Erro ao enviar GIF: {e}")
            return False
    
    def _generate_single_day_diagram(self, voos, titulo, output_path):
        """
        Gera diagrama visual das rotas para um dia especifico com icones dos helicopteros
        """
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        from PIL import Image
        import numpy as np
        from datetime import datetime
        import os
        
        helicopteros = ['PR-OMB', 'PR-OMH', 'PR-OOE']
        cores = {'PR-OMB': '#3B82F6', 'PR-OMH': '#10B981', 'PR-OOE': '#F59E0B'}
        modelos = {'PR-OMB': 'EC155', 'PR-OMH': 'EC155', 'PR-OOE': 'EC135'}
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        ec155_path = os.path.join(script_dir, 'ec155_icon.png')
        ec135_path = os.path.join(script_dir, 'ec135_icon.png')
        
        def remove_checkered_background(img):
            """Remove fundo xadrez cinza/branco e sombras, torna transparente"""
            from scipy import ndimage
            img_array = np.array(img.convert('RGBA'))
            r, g, b, a = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2], img_array[:,:,3]
            
            is_gray = (abs(r.astype(int) - g.astype(int)) < 25) & (abs(g.astype(int) - b.astype(int)) < 25)
            is_light = (r.astype(int) > 120) & (g.astype(int) > 120) & (b.astype(int) > 120)
            
            checkered_mask = is_gray & is_light
            
            eroded_mask = ndimage.binary_dilation(checkered_mask, iterations=1)
            
            img_array[eroded_mask, 3] = 0
            
            return Image.fromarray(img_array)
        
        def load_helicopter_image(path):
            """Carrega imagem PNG e remove fundo xadrez"""
            try:
                img = Image.open(path).convert('RGBA')
                img = remove_checkered_background(img)
                return img
            except:
                return None
        
        ec155_img = load_helicopter_image(ec155_path)
        ec135_img = load_helicopter_image(ec135_path)
        
        voos_por_heli = {h: [] for h in helicopteros}
        
        for voo in (voos or []):
            prefixo = _extrair_prefixo(voo)

            if prefixo in helicopteros:
                voos_por_heli[prefixo].append(voo)
        
        fig, ax = plt.subplots(figsize=(14, 5))
        fig.patch.set_facecolor('#0f172a')
        ax.set_facecolor('#0f172a')
        
        y_spacing = 1.5
        y_positions = {h: (len(helicopteros) - i - 0.5) * y_spacing for i, h in enumerate(helicopteros)}
        
        for idx, heli in enumerate(helicopteros):
            voos_heli = sorted(voos_por_heli[heli], key=lambda v: v.get('DataHoraVoo__c', ''))
            cor = cores.get(heli, '#888888')
            modelo = modelos.get(heli, '')
            y_pos = y_positions[heli]
            
            ax.axhline(y=y_pos, color='#334155', linestyle='-', linewidth=0.5, alpha=0.3)
            
            heli_img = ec135_img if heli == 'PR-OOE' else ec155_img
            if heli_img:
                img_array = np.array(heli_img)
                imagebox = OffsetImage(img_array, zoom=0.08)
                ab = AnnotationBbox(imagebox, (-1.8, y_pos), frameon=False, box_alignment=(0.5, 0.5))
                ax.add_artist(ab)
            
            ax.text(-0.3, y_pos + 0.15, heli, fontsize=11, fontweight='bold', 
                   color='white', ha='left', va='center', family='monospace')
            ax.text(-0.3, y_pos - 0.15, modelo, fontsize=8, 
                   color='#94a3b8', ha='left', va='center')
            
            if not voos_heli:
                ax.text(4.5, y_pos, 'sem voos programados', fontsize=10, 
                       color='#475569', ha='center', va='center', style='italic')
                continue
            
            for i, voo in enumerate(voos_heli):
                data_hora = voo.get('DataHoraVoo__c', '')
                try:
                    dt = datetime.fromisoformat(data_hora.replace('Z', '+00:00'))
                    dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                    hora_str = dt_local.strftime('%H:%M')
                except:
                    hora_str = '??:??'
                
                rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or ''
                partes = rota.replace(' > ', '-').replace(' - ', '-').split('-')
                if len(partes) >= 2:
                    origem = partes[0].strip()[:4]
                    destino = partes[-1].strip()[:4]
                    rota_curta = f"{origem}-{destino}"
                else:
                    rota_curta = rota[:10] if rota else '?'
                
                x_pos = i * 2.2 + 1.5
                
                rect = mpatches.FancyBboxPatch(
                    (x_pos - 0.8, y_pos - 0.4), 1.6, 0.8,
                    boxstyle="round,pad=0.02,rounding_size=0.1",
                    facecolor='#1e293b', edgecolor=cor, alpha=0.95, linewidth=2
                )
                ax.add_patch(rect)
                
                ax.text(x_pos, y_pos + 0.15, hora_str, fontsize=11, 
                       color=cor, ha='center', va='center', fontweight='bold')
                ax.text(x_pos, y_pos - 0.15, rota_curta, fontsize=9, 
                       color='#cbd5e1', ha='center', va='center', family='monospace')
                
                if i < len(voos_heli) - 1:
                    ax.annotate('', xy=(x_pos + 1.0, y_pos), xytext=(x_pos + 0.85, y_pos),
                               arrowprops=dict(arrowstyle='->', color='#475569', lw=1.5))
        
        ax.text(4.5, len(helicopteros) * y_spacing + 0.4, titulo, fontsize=14, 
               fontweight='bold', color='white', ha='center', va='center')
        
        max_voos = max(len(v) for v in voos_por_heli.values()) if voos_por_heli else 1
        ax.set_xlim(-3, max(10, max_voos * 2.2 + 2.5))
        ax.set_ylim(0, len(helicopteros) * y_spacing + 0.9)
        ax.axis('off')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#0f172a', edgecolor='none', 
                   bbox_inches='tight', pad_inches=0.2)
        plt.close()
        
        return output_path
    
    def generate_helicopter_routes_chart(self, voos_hoje, voos_amanha=None, voos_depois_amanha=None, voos_proximos_dias=None):
        """
        Gera diagramas separados: um para hoje, amanha, depois de amanha e proximos dias
        Retorna lista de caminhos dos arquivos gerados
        """
        from datetime import datetime

        charts = []

        hoje_str = datetime.now().strftime('%d/%m/%Y')
        amanha_str = (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')
        depois_amanha_str = (datetime.now() + timedelta(days=2)).strftime('%d/%m/%Y')

        if voos_hoje:
            path_hoje = self._generate_single_day_diagram(
                voos_hoje,
                f'ROTAS HOJE - {hoje_str}',
                'chart_helicopteros_hoje.png'
            )
            charts.append(path_hoje)
            logging.info(f"Diagrama de hoje gerado: {path_hoje}")

        if voos_amanha:
            path_amanha = self._generate_single_day_diagram(
                voos_amanha,
                f'ROTAS AMANHA - {amanha_str}',
                'chart_helicopteros_amanha.png'
            )
            charts.append(path_amanha)
            logging.info(f"Diagrama de amanha gerado: {path_amanha}")

        if voos_depois_amanha:
            path_depois = self._generate_single_day_diagram(
                voos_depois_amanha,
                f'ROTAS DEPOIS DE AMANHA - {depois_amanha_str}',
                'chart_helicopteros_depois_amanha.png'
            )
            charts.append(path_depois)
            logging.info(f"Diagrama de depois de amanha gerado: {path_depois}")

        if voos_proximos_dias:
            for dia_info in voos_proximos_dias:
                label = dia_info['label']
                dia_voos = dia_info['voos']
                date_str = dia_info['date'].strftime('%d%m')
                filename = f'chart_helicopteros_{date_str}.png'
                path_dia = self._generate_single_day_diagram(
                    dia_voos,
                    f'ROTAS {label.upper()}',
                    filename
                )
                charts.append(path_dia)
                logging.info(f"Diagrama de {label} gerado: {path_dia}")

        return charts if charts else None
    
    def _render_map(self, ax, pontos_mostrar, rotas_por_heli, helicopteros, cores, titulo, use_osm, zoom=12):
        """Renderiza um mapa com os pontos e rotas especificados usando curvas para evitar sobreposicao"""
        import matplotlib.patches as mpatches
        from matplotlib.lines import Line2D
        from matplotlib.patches import FancyArrowPatch
        from matplotlib.path import Path
        import matplotlib.patches as patches
        import numpy as np
        
        try:
            import contextily as ctx
        except ImportError:
            use_osm = False
        
        if use_osm:
            try:
                ctx.add_basemap(ax, crs='EPSG:4326', 
                               source=ctx.providers.CartoDB.Positron, zoom=zoom)
            except Exception as e:
                logging.warning(f"Erro ao baixar tiles: {e}")
                ax.set_facecolor('#f5f5f5')
        else:
            ax.set_facecolor('#f5f5f5')
        
        for icao in pontos_mostrar:
            if icao not in HELIPONTOS:
                continue
            info = HELIPONTOS[icao]
            
            ax.plot(info['lon'], info['lat'], 's', markersize=10, 
                   color='#1a1a1a', markeredgecolor='white', markeredgewidth=2, zorder=10)
            
            nome_curto = info.get('nome', icao)[:15]
            label_text = f"{icao}\n{nome_curto}"
            ax.annotate(label_text, (info['lon'], info['lat']), 
                       xytext=(8, 8), textcoords='offset points',
                       fontsize=7, fontweight='bold', color='#1a1a1a',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                                alpha=0.95, edgecolor='#cccccc', linewidth=0.5),
                       zorder=11)
        
        route_count = {}
        for heli in helicopteros:
            for rota_info in rotas_por_heli.get(heli, []):
                icaos = rota_info['icaos']
                for i in range(len(icaos) - 1):
                    key = tuple(sorted([icaos[i], icaos[i+1]]))
                    route_count[key] = route_count.get(key, 0) + 1
        
        route_drawn = {}
        
        def draw_curved_arrow(ax, lon1, lat1, lon2, lat2, color, curve_amount=0.15, linewidth=2.5):
            """Desenha uma seta curva entre dois pontos usando curva de Bezier"""
            mid_lon = (lon1 + lon2) / 2
            mid_lat = (lat1 + lat2) / 2
            
            dx = lon2 - lon1
            dy = lat2 - lat1
            
            perp_x = -dy * curve_amount
            perp_y = dx * curve_amount
            
            ctrl_lon = mid_lon + perp_x
            ctrl_lat = mid_lat + perp_y
            
            t = np.linspace(0, 1, 50)
            bezier_lon = (1-t)**2 * lon1 + 2*(1-t)*t * ctrl_lon + t**2 * lon2
            bezier_lat = (1-t)**2 * lat1 + 2*(1-t)*t * ctrl_lat + t**2 * lat2
            
            ax.plot(bezier_lon, bezier_lat, color=color, linewidth=linewidth, 
                   alpha=0.85, zorder=5, solid_capstyle='round')
            
            arrow_t = 0.85
            arrow_lon = (1-arrow_t)**2 * lon1 + 2*(1-arrow_t)*arrow_t * ctrl_lon + arrow_t**2 * lon2
            arrow_lat = (1-arrow_t)**2 * lat1 + 2*(1-arrow_t)*arrow_t * ctrl_lat + arrow_t**2 * lat2
            
            end_t = 0.95
            end_lon = (1-end_t)**2 * lon1 + 2*(1-end_t)*end_t * ctrl_lon + end_t**2 * lon2
            end_lat = (1-end_t)**2 * lat1 + 2*(1-end_t)*end_t * ctrl_lat + end_t**2 * lat2
            
            ax.annotate('', xy=(end_lon, end_lat), xytext=(arrow_lon, arrow_lat),
                       arrowprops=dict(arrowstyle='-|>', color=color, lw=2, mutation_scale=12),
                       zorder=6)
            
            label_t = 0.5
            label_lon = (1-label_t)**2 * lon1 + 2*(1-label_t)*label_t * ctrl_lon + label_t**2 * lon2
            label_lat = (1-label_t)**2 * lat1 + 2*(1-label_t)*label_t * ctrl_lat + label_t**2 * lat2
            
            return label_lon, label_lat
        
        curve_variations = [0.12, -0.12, 0.25, -0.25, 0.35, -0.35]
        heli_curve_idx = {h: i for i, h in enumerate(helicopteros)}
        
        for heli in helicopteros:
            cor = cores.get(heli, '#888888')
            base_curve = curve_variations[heli_curve_idx.get(heli, 0) % len(curve_variations)]
            
            for rota_idx, rota_info in enumerate(rotas_por_heli.get(heli, [])):
                icaos = rota_info['icaos']
                hora = rota_info['hora']
                
                for i in range(len(icaos) - 1):
                    orig = icaos[i]
                    dest = icaos[i + 1]
                    
                    if orig in HELIPONTOS and dest in HELIPONTOS:
                        lat1, lon1 = HELIPONTOS[orig]['lat'], HELIPONTOS[orig]['lon']
                        lat2, lon2 = HELIPONTOS[dest]['lat'], HELIPONTOS[dest]['lon']
                        
                        route_key = (orig, dest)
                        reverse_key = (dest, orig)
                        
                        times_drawn = route_drawn.get(route_key, 0) + route_drawn.get(reverse_key, 0)
                        
                        if times_drawn == 0:
                            curve = base_curve
                        else:
                            curve = base_curve + (times_drawn * 0.08) * (1 if times_drawn % 2 == 0 else -1)
                        
                        if reverse_key in route_drawn:
                            curve = -abs(curve) if curve > 0 else abs(curve)
                        
                        label_lon, label_lat = draw_curved_arrow(
                            ax, lon1, lat1, lon2, lat2, cor, 
                            curve_amount=curve, linewidth=2.5
                        )
                        
                        route_drawn[route_key] = route_drawn.get(route_key, 0) + 1
                        
                        if hora and i == 0:
                            ax.annotate(f"{hora}", (label_lon, label_lat + 0.005),
                                       fontsize=8, fontweight='bold', color='white',
                                       ha='center', va='center',
                                       bbox=dict(boxstyle='round,pad=0.2', facecolor=cor, 
                                                alpha=0.95, edgecolor='white', linewidth=1.5),
                                       zorder=15)
        
        legend_elements = []
        for h in helicopteros:
            legend_elements.append(
                Line2D([0], [0], color=cores[h], linewidth=3, label=h)
            )
        
        legend = ax.legend(handles=legend_elements, loc='upper right', fontsize=10, 
                          facecolor='white', edgecolor='#cccccc', framealpha=0.95,
                          title='Aeronaves', title_fontsize=10)
        legend.set_zorder(20)
        
        ax.set_title(titulo, fontsize=14, fontweight='bold', 
                    pad=10, bbox=dict(boxstyle='round,pad=0.4', facecolor='white', 
                                     alpha=0.95, edgecolor='#cccccc'))
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.tick_params(axis='both', labelsize=0)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)

    def generate_routes_map(self, voos_hoje, voos_amanha=None, voos_depois_amanha=None, voos_proximos_dias=None):
        """
        Gera mapa focado nas rotas reais
        Calcula limites dinamicamente baseado nos pontos utilizados
        """
        import matplotlib.pyplot as plt
        from datetime import datetime

        try:
            import contextily as ctx
            use_osm = True
        except ImportError:
            use_osm = False
            logging.warning("contextily nao disponivel, mapa sem fundo OSM")

        helicopteros = ['PR-OMB', 'PR-OMH', 'PR-OOE']
        cores = {'PR-OMB': '#3B82F6', 'PR-OMH': '#10B981', 'PR-OOE': '#F59E0B'}

        SP_CENTER_LAT = -23.58
        SP_CENTER_LON = -46.68

        todos_voos = list(voos_hoje or [])
        if voos_amanha:
            todos_voos.extend(voos_amanha)
        if voos_depois_amanha:
            todos_voos.extend(voos_depois_amanha)
        if voos_proximos_dias:
            for dia_info in voos_proximos_dias:
                todos_voos.extend(dia_info['voos'])
        
        if not todos_voos:
            return None
        
        rotas_por_heli = {h: [] for h in helicopteros}
        pontos_usados = set()
        
        for voo in todos_voos:
            prefixo = _extrair_prefixo(voo)

            if prefixo not in helicopteros:
                continue
            
            rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or ''
            partes = rota.replace(' > ', '-').replace(' - ', '-').split('-')
            
            icaos = []
            for p in partes:
                icao = p.strip().upper()[:4]
                if icao in HELIPONTOS:
                    icaos.append(icao)
                    pontos_usados.add(icao)
            
            data_hora = voo.get('DataHoraVoo__c', '')
            hora_str = ''
            try:
                dt = datetime.fromisoformat(data_hora.replace('Z', '+00:00'))
                dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                hora_str = dt_local.strftime('%H:%M')
            except:
                pass
            
            if len(icaos) >= 2:
                rotas_por_heli[prefixo].append({'icaos': icaos, 'hora': hora_str})
        
        if not pontos_usados:
            return None
        
        pontos_sp = set()
        pontos_distantes = set()
        
        for icao in pontos_usados:
            info = HELIPONTOS.get(icao, {})
            lat = info.get('lat', 0)
            lon = info.get('lon', 0)
            
            if abs(lat - SP_CENTER_LAT) < 0.25 and abs(lon - SP_CENTER_LON) < 0.25:
                pontos_sp.add(icao)
            else:
                pontos_distantes.add(icao)
        
        maps_generated = []
        hoje_str = datetime.now().strftime('%d/%m/%Y')
        
        if pontos_sp:
            lats_sp = [HELIPONTOS[icao]['lat'] for icao in pontos_sp if icao in HELIPONTOS]
            lons_sp = [HELIPONTOS[icao]['lon'] for icao in pontos_sp if icao in HELIPONTOS]
            
            if lats_sp and lons_sp:
                min_lat, max_lat = min(lats_sp), max(lats_sp)
                min_lon, max_lon = min(lons_sp), max(lons_sp)
                
                lat_range = max_lat - min_lat
                lon_range = max_lon - min_lon
                
                margin_lat = max(lat_range * 0.3, 0.03)
                margin_lon = max(lon_range * 0.3, 0.03)
                
                center_lat = (min_lat + max_lat) / 2
                center_lon = (min_lon + max_lon) / 2
                
                half_size = max(lat_range / 2 + margin_lat, lon_range / 2 + margin_lon, 0.06)
                
                fig, ax = plt.subplots(figsize=(10, 10))
                
                ax.set_xlim(center_lon - half_size, center_lon + half_size)
                ax.set_ylim(center_lat - half_size, center_lat + half_size)
                
                self._render_map(ax, pontos_sp, rotas_por_heli, helicopteros, cores, 
                               f'SP METROPOLITANA - {hoje_str}', use_osm, zoom=13)
                
                plt.tight_layout()
                map_sp_path = 'chart_mapa.png'
                plt.savefig(map_sp_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
                plt.close()
                
                logging.info(f"Mapa SP gerado: {map_sp_path}")
                maps_generated.append(map_sp_path)
        
        if pontos_distantes:
            fig, ax = plt.subplots(figsize=(10, 10))
            
            todos_pontos = pontos_sp | pontos_distantes
            lats = [HELIPONTOS[p]['lat'] for p in todos_pontos if p in HELIPONTOS]
            lons = [HELIPONTOS[p]['lon'] for p in todos_pontos if p in HELIPONTOS]
            
            if lats and lons:
                lat_range = max(lats) - min(lats)
                lon_range = max(lons) - min(lons)
                
                margin = max(lat_range, lon_range) * 0.15 + 0.05
                
                center_lat = (min(lats) + max(lats)) / 2
                center_lon = (min(lons) + max(lons)) / 2
                half_size = max(lat_range, lon_range) / 2 + margin
                
                ax.set_xlim(center_lon - half_size, center_lon + half_size)
                ax.set_ylim(center_lat - half_size, center_lat + half_size)
                
                self._render_map(ax, todos_pontos, rotas_por_heli, helicopteros, cores, 
                               f'VISAO GERAL - {hoje_str}', use_osm, zoom=9)
                
                plt.tight_layout()
                map_geral_path = 'chart_mapa_geral.png'
                plt.savefig(map_geral_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
                plt.close()
                
                logging.info(f"Mapa geral gerado: {map_geral_path}")
                maps_generated.append(map_geral_path)
        
        return maps_generated if maps_generated else None
    
    def generate_revenue_chart(self, df):
        """Gera gráfico de receita ao longo do mês"""
        valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
        
        df['Voo_Data'] = pd.to_datetime(df['Voo_DataHora']).dt.date
        df['Categoria'] = df['Voo_Tipo'].apply(
            lambda x: 'Charter' if 'charter' in str(x).lower() else 'Shuttle'
        )
        
        # Agrupar por dia e categoria
        df_dia = df.groupby(['Voo_Data', 'Categoria'])[valor_col].sum().reset_index()
        df_dia.columns = ['Data', 'Categoria', 'Receita']
        
        # Criar gráfico
        fig = px.bar(
            df_dia,
            x='Data',
            y='Receita',
            color='Categoria',
            title='Receita por Dia - Fevereiro 2026',
            color_discrete_map={'Charter': '#F59E0B', 'Shuttle': '#3B82F6'},
            barmode='stack'
        )
        
        fig.update_layout(
            xaxis_title='Data',
            yaxis_title='Receita (R$)',
            legend_title='Tipo',
            font=dict(size=14),
            height=500,
            width=900,
            plot_bgcolor='white',
            yaxis_tickformat=',.0f',
            yaxis_tickprefix='R$ '
        )
        
        # Salvar
        chart_path = 'chart_receita.png'
        fig.write_image(chart_path, scale=2)
        logging.info(f"Gráfico de receita gerado: {chart_path}")
        return chart_path
    
    def generate_monthly_route_map(self, df):
        """Gera mapa de rotas mensal agregado (plotly)"""
        valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
        
        # Processar rotas
        rotas_data = []
        helipontos_usados = {}
        
        for _, row in df.iterrows():
            rota = str(row['Voo_Rota'])
            partes = [p.strip() for p in rota.replace('>', ' ').split()]
            
            if len(partes) >= 2:
                origem = partes[0]
                destino = partes[-1]
                
                if origem in HELIPONTOS and destino in HELIPONTOS:
                    rotas_data.append({
                        'origem': origem,
                        'destino': destino,
                        'origem_lat': HELIPONTOS[origem]['lat'],
                        'origem_lon': HELIPONTOS[origem]['lon'],
                        'destino_lat': HELIPONTOS[destino]['lat'],
                        'destino_lon': HELIPONTOS[destino]['lon'],
                        'valor': row[valor_col],
                        'tipo': row['Voo_Tipo']
                    })
                    
                    # Acumular receita por heliponto
                    for h in [origem, destino]:
                        if h not in helipontos_usados:
                            helipontos_usados[h] = {'receita': 0, 'voos': 0}
                        helipontos_usados[h]['receita'] += row[valor_col] / 2
                        helipontos_usados[h]['voos'] += 0.5
        
        if not rotas_data:
            return None
        
        # Criar mapa
        fig = go.Figure()
        
        # Adicionar linhas das rotas
        for rota in rotas_data:
            cor = '#F59E0B' if 'charter' in str(rota['tipo']).lower() else '#3B82F6'
            fig.add_trace(go.Scattergeo(
                lon=[rota['origem_lon'], rota['destino_lon']],
                lat=[rota['origem_lat'], rota['destino_lat']],
                mode='lines',
                line=dict(width=2, color=cor),
                opacity=0.6,
                showlegend=False
            ))
        
        # Adicionar pontos dos helipontos
        for codigo, dados in helipontos_usados.items():
            h = HELIPONTOS[codigo]
            tamanho = max(10, min(30, dados['receita'] / 30000))
            fig.add_trace(go.Scattergeo(
                lon=[h['lon']],
                lat=[h['lat']],
                mode='markers+text',
                marker=dict(size=tamanho, color='#10B981', line=dict(width=1, color='white')),
                text=codigo,
                textposition='top center',
                textfont=dict(size=10, color='black'),
                name=h['nome'],
                showlegend=False
            ))
        
        fig.update_layout(
            title='🗺️ Mapa de Rotas - Fevereiro 2026',
            geo=dict(
                scope='south america',
                center=dict(lat=-23.3, lon=-46.5),
                projection_scale=15,
                showland=True,
                landcolor='rgb(243, 243, 243)',
                countrycolor='rgb(204, 204, 204)',
                showocean=True,
                oceancolor='rgb(230, 245, 255)'
            ),
            height=600,
            width=900,
            font=dict(size=14)
        )
        
        # Salvar
        map_path = 'chart_mapa.png'
        fig.write_image(map_path, scale=2)
        logging.info(f"Mapa de rotas gerado: {map_path}")
        return map_path
    
    def generate_helicopter_chart(self, df):
        """Gera gráfico de receita por helicóptero (prefixo)"""
        valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
        
        # Extrair apenas o sufixo do prefixo (OMB, OMH, OOE, HAH)
        df['Helicoptero'] = df['Voo_Prefixo'].apply(
            lambda x: str(x).replace('PR-', '').replace('PS-', '') if pd.notna(x) else 'N/A'
        )
        
        # Agrupar por helicóptero
        df_heli = df.groupby('Helicoptero').agg({
            valor_col: 'sum',
            'Codigo_Reserva': 'count'
        }).reset_index()
        df_heli.columns = ['Helicoptero', 'Receita', 'Voos']
        df_heli = df_heli.sort_values('Receita', ascending=True)
        
        # Cores personalizadas para cada helicóptero
        cores = {
            'OMB': '#3B82F6',   # Azul
            'OMH': '#10B981',   # Verde
            'OOE': '#F59E0B',   # Laranja
            'HAH': '#8B5CF6'    # Roxo
        }
        df_heli['Cor'] = df_heli['Helicoptero'].map(cores).fillna('#6B7280')
        
        # Criar gráfico
        fig = go.Figure()
        
        fig.add_trace(go.Bar(
            y=df_heli['Helicoptero'],
            x=df_heli['Receita'],
            orientation='h',
            marker_color=df_heli['Cor'],
            text=df_heli.apply(lambda x: f"R$ {x['Receita']:,.0f} ({int(x['Voos'])} voos)", axis=1),
            textposition='inside',
            textfont=dict(color='white', size=14)
        ))
        
        fig.update_layout(
            title='Receita por Helicoptero - Fevereiro 2026',
            xaxis_title='Receita (R$)',
            yaxis_title='Prefixo',
            font=dict(size=14),
            height=400,
            width=900,
            plot_bgcolor='white',
            xaxis_tickformat=',.0f',
            xaxis_tickprefix='R$ ',
            showlegend=False
        )
        
        # Salvar
        chart_path = 'chart_helicopteros.png'
        fig.write_image(chart_path, scale=2)
        logging.info(f"Gráfico de helicópteros gerado: {chart_path}")
        return chart_path
    
    def send_charts(self, df):
        """Gera e envia gráficos para o Telegram"""
        logging.info("Gerando gráficos...")
        
        # Gráfico de receita por dia
        try:
            chart_path = self.generate_revenue_chart(df)
            self.send_photo(chart_path, '📊 <b>Receita por Dia - Fevereiro 2026</b>\n🟠 Charter | 🔵 Shuttle')
        except Exception as e:
            logging.error(f"Erro ao gerar gráfico de receita: {e}")
        
        # Gráfico por helicóptero
        try:
            heli_path = self.generate_helicopter_chart(df)
            self.send_photo(heli_path, '🚁 <b>Receita por Helicóptero - Fevereiro 2026</b>\nPR-OMB | PR-OMH | PR-OOE | PS-HAH')
        except Exception as e:
            logging.error(f"Erro ao gerar gráfico de helicópteros: {e}")
        
        # Mapa de rotas
        try:
            map_path = self.generate_monthly_route_map(df)
            if map_path:
                self.send_photo(map_path, '🗺️ <b>Mapa de Rotas - Fevereiro 2026</b>\n🟢 Helipontos ativos')
        except Exception as e:
            logging.error(f"Erro ao gerar mapa: {e}")
        
        logging.info("Gráficos enviados!")
        return True
    
    def load_state(self):
        """Carrega estado anterior para comparação"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Erro ao carregar estado: {e}")
        return {'voos': [], 'last_check': None}
    
    def save_state(self, state):
        """Salva estado atual"""
        try:
            state['last_check'] = datetime.now().isoformat()
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Erro ao salvar estado: {e}")
    
    def format_currency(self, value):
        """Formata valores monetários - delegado para utils"""
        return utils_format_currency(value)
    
    def notify_new_flight(self, voo):
        """Notifica sobre novo voo criado"""
        message = f"""
🚁 <b>NOVO VOO CRIADO</b>

📅 <b>Data:</b> {voo.get('data', 'N/A')}
🛫 <b>Rota:</b> {voo.get('rota', 'N/A')}
✈️ <b>Tipo:</b> {voo.get('tipo', 'N/A')}
👥 <b>Passageiros:</b> {voo.get('passageiros', 'N/A')}
💰 <b>Valor:</b> {self.format_currency(voo.get('valor', 0))}
🎫 <b>Reserva:</b> {voo.get('reserva', 'N/A')}
📍 <b>Prefixo:</b> {voo.get('prefixo', 'N/A')}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
        return self.send_message(message)
    
    def notify_cancelled_flight(self, voo):
        """Notifica sobre voo cancelado"""
        message = f"""
❌ <b>VOO CANCELADO</b>

📅 <b>Data:</b> {voo.get('data', 'N/A')}
🛫 <b>Rota:</b> {voo.get('rota', 'N/A')}
✈️ <b>Tipo:</b> {voo.get('tipo', 'N/A')}
💰 <b>Valor Perdido:</b> {self.format_currency(voo.get('valor', 0))}
🎫 <b>Reserva:</b> {voo.get('reserva', 'N/A')}
📝 <b>Motivo:</b> {voo.get('motivo', 'Não informado')}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
        return self.send_message(message)
    
    def notify_daily_summary(self, dados):
        """Envia resumo diário"""
        message = f"""
📊 <b>RESUMO DIÁRIO - REVO</b>
📅 {datetime.now().strftime('%d/%m/%Y')}

━━━━━━━━━━━━━━━━━━━━━━

📈 <b>FEVEREIRO 2026</b>

🎫 <b>Total Reservas:</b> {dados.get('total_reservas', 0)}
🚁 <b>Total Voos:</b> {dados.get('total_voos', 0)}
👥 <b>Total Passageiros:</b> {dados.get('total_passageiros', 0)}

💰 <b>Receita Total:</b> {self.format_currency(dados.get('receita_total', 0))}
💵 <b>Receita Charter:</b> {self.format_currency(dados.get('receita_charter', 0))}
💵 <b>Receita Shuttle:</b> {self.format_currency(dados.get('receita_shuttle', 0))}

━━━━━━━━━━━━━━━━━━━━━━

📅 <b>PRÓXIMOS 7 DIAS</b>

🚁 <b>Voos Programados:</b> {dados.get('voos_proximos_7d', 0)}
💰 <b>Receita Esperada:</b> {self.format_currency(dados.get('receita_proximos_7d', 0))}

━━━━━━━━━━━━━━━━━━━━━━

🗓️ <b>VOOS DE HOJE ({dados.get('data_hoje', '')})</b>

🚁 <b>Total de Voos:</b> {dados.get('voos_hoje', 0)}
👥 <b>Passageiros:</b> {dados.get('pax_hoje', 0)}
💰 <b>Receita:</b> {self.format_currency(dados.get('receita_hoje', 0))}

{dados.get('lista_voos_hoje', 'Nenhum voo hoje')}

━━━━━━━━━━━━━━━━━━━━━━

🏆 <b>TOP 3 ROTAS DO MÊS</b>
{dados.get('top_rotas', 'N/A')}

⏰ Atualizado em {datetime.now().strftime('%H:%M')}
"""
        return self.send_message(message)
    
    def check_for_changes(self, df_new, send_diagrams=True):
        """Verifica mudanças entre estados e notifica apenas voos futuros (sem duplicatas)"""
        state = self.load_state()
        previous_voos = set(state.get('voos', []))
        
        agora = pd.Timestamp.now(tz='UTC')
        
        df_new['Voo_DataHora'] = pd.to_datetime(df_new['Voo_DataHora'], errors='coerce', utc=True)
        df_futuros = df_new[df_new['Voo_DataHora'] >= agora].copy()
        
        if 'Voo_Id' in df_futuros.columns:
            df_voos_unicos = df_futuros.drop_duplicates(subset=['Voo_Id']).copy()
        else:
            df_voos_unicos = df_futuros.drop_duplicates(subset=['Voo_DataHora', 'Voo_Rota']).copy()
        
        current_voos = set()
        voo_data_map = {}
        for _, row in df_voos_unicos.iterrows():
            voo_id_sf = row.get('Voo_Id', '')
            if voo_id_sf:
                voo_key = str(voo_id_sf)
            else:
                voo_key = f"{row.get('Voo_DataHora', '')}_{row.get('Voo_Rota', '')}"
            current_voos.add(voo_key)
            voo_data_map[voo_key] = row
        
        new_voos = current_voos - previous_voos
        cancelled_voos = previous_voos - current_voos
        
        novos_count = 0
        cancelados_count = 0
        
        for voo_key in new_voos:
            row = voo_data_map.get(voo_key)
            if row is not None:
                pax = row.get('Voo_Contador_Passageiros', 0)
                if 'Voo_Id' in df_futuros.columns:
                    pax_total = df_futuros[df_futuros['Voo_Id'] == row.get('Voo_Id')]['Valor_Total'].count()
                    pax = max(pax, pax_total)
                
                receita_voo = 0
                if 'Voo_Id' in df_futuros.columns:
                    receita_voo = df_futuros[df_futuros['Voo_Id'] == row.get('Voo_Id')]['Valor_Total'].sum()
                else:
                    receita_voo = row.get('Valor_Total', 0)
                
                voo_info = {
                    'data': str(row.get('Voo_DataHora', 'N/A'))[:16],
                    'rota': row.get('Voo_Rota_Extenso', row.get('Voo_Rota', 'N/A')),
                    'tipo': row.get('Voo_Tipo', 'N/A'),
                    'passageiros': int(pax) if pd.notna(pax) else 0,
                    'valor': receita_voo,
                    'reserva': row.get('Voo_Numero', row.get('Voo_Id', 'N/A')),
                    'prefixo': row.get('Voo_Prefixo', 'N/A')
                }
                self.notify_new_flight(voo_info)
                novos_count += 1
        
        for voo_key in cancelled_voos:
            if voo_key.startswith('a0'):
                continue
            
            parts = voo_key.split('_')
            if len(parts) >= 2:
                try:
                    data_voo = pd.to_datetime(parts[0], utc=True)
                    if data_voo < agora:
                        continue
                except:
                    pass
            
            voo_info = {
                'data': parts[0] if parts else 'N/A',
                'rota': parts[1] if len(parts) > 1 else 'N/A',
                'tipo': 'N/A',
                'valor': 0,
                'reserva': voo_key[:20],
                'motivo': 'Removido do sistema'
            }
            self.notify_cancelled_flight(voo_info)
            cancelados_count += 1
        
        state['voos'] = list(current_voos)
        self.save_state(state)
        
        if send_diagrams and (novos_count > 0 or cancelados_count > 0):
            try:
                self._send_updated_diagrams()
            except Exception as e:
                logging.error(f"Erro ao enviar diagramas atualizados: {e}")
        
        logging.info(f"Verificação concluída: {novos_count} novos, {cancelados_count} cancelados")
        return novos_count, cancelados_count
    
    def _send_updated_diagrams(self):
        """Busca voos atualizados e envia diagramas"""
        from telegram_notifier import get_voos_salesforce

        voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias = get_voos_salesforce()

        chart_paths = self.generate_helicopter_routes_chart(voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias)
        if chart_paths:
            for chart_path in chart_paths:
                if 'hoje' in chart_path:
                    self.send_photo(chart_path, "Rotas Atualizadas - Hoje")
                elif 'depois' in chart_path:
                    self.send_photo(chart_path, "Rotas Atualizadas - Depois de Amanha")
                elif 'amanha' in chart_path:
                    self.send_photo(chart_path, "Rotas Atualizadas - Amanha")
                else:
                    self.send_photo(chart_path, "Rotas Atualizadas - Proximos Dias")

        map_paths = self.generate_routes_map(voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias)
        if map_paths:
            for map_path in map_paths:
                if 'geral' in map_path:
                    self.send_photo(map_path, "Mapa Atualizado - Geral")
                else:
                    self.send_photo(map_path, "Mapa Atualizado - SP")
    
    def generate_daily_summary(self, df):
        """Gera e envia resumo diário completo"""
        valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
        pax_col = 'Qtd_Passageiros_Reserva' if 'Qtd_Passageiros_Reserva' in df.columns else 'Voo_Contador_Passageiros'
        
        df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
        df['Categoria'] = df['Voo_Tipo'].apply(
            lambda x: 'Charter' if 'charter' in str(x).lower() else 'Shuttle'
        )
        
        hoje = datetime.now().date()
        amanha = hoje + timedelta(days=1)
        proximos_7d = hoje + timedelta(days=7)
        mes_atual = datetime.now().month
        ano_atual = datetime.now().year
        
        df['Voo_Data'] = pd.to_datetime(df['Voo_DataHora']).dt.date
        df_mes = df[(pd.to_datetime(df['Voo_DataHora']).dt.month == mes_atual) & 
                    (pd.to_datetime(df['Voo_DataHora']).dt.year == ano_atual)]
        df_proximos = df[(df['Voo_Data'] >= hoje) & (df['Voo_Data'] <= proximos_7d)]
        df_hoje = df[df['Voo_Data'] == hoje]
        df_amanha = df[df['Voo_Data'] == amanha]
        
        top_rotas = df_mes.groupby('Voo_Rota_ICAO' if 'Voo_Rota_ICAO' in df_mes.columns else 'Voo_Rota')[valor_col].sum().sort_values(ascending=False).head(3)
        top_rotas_str = "\n".join([f"  {rota}: {self.format_currency(valor)}" for rota, valor in top_rotas.items()])
        
        lista_voos_hoje = self._format_flight_list(df_hoje)
        lista_voos_amanha = self._format_flight_list(df_amanha)
        
        MESES = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril', 5: 'Maio', 6: 'Junho',
                 7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
        
        message = f"""
<b>RESUMO DIARIO - REVO</b>
{datetime.now().strftime('%d/%m/%Y')}

<b>{MESES[mes_atual].upper()} {ano_atual}</b>

Reservas: {len(df_mes)}
Voos: {df_mes['Voo_Id'].nunique() if 'Voo_Id' in df_mes.columns else len(df_mes)}
Passageiros: {int(df_mes[pax_col].sum())}

Receita Total: {self.format_currency(df_mes[valor_col].sum())}
  Charter: {self.format_currency(df_mes[df_mes['Categoria'] == 'Charter'][valor_col].sum())}
  Shuttle: {self.format_currency(df_mes[df_mes['Categoria'] == 'Shuttle'][valor_col].sum())}

<b>HOJE ({hoje.strftime('%d/%m')}): {len(df_hoje)} voos</b>
{lista_voos_hoje}

<b>AMANHA ({amanha.strftime('%d/%m')}): {len(df_amanha)} voos</b>
{lista_voos_amanha}

<b>PROXIMOS 7 DIAS</b>
Voos: {len(df_proximos)}
Receita: {self.format_currency(df_proximos[valor_col].sum())}

<b>TOP 3 ROTAS DO MES</b>
{top_rotas_str}

Atualizado: {datetime.now().strftime('%H:%M')}
"""
        return self.send_message(message)
    
    def _format_flight_list(self, df_voos):
        """Formata lista de voos para mensagem"""
        if df_voos.empty:
            return "Nenhum voo"
        
        lista = ""
        for _, voo in df_voos.head(8).iterrows():
            hora = pd.to_datetime(voo['Voo_DataHora']).strftime('%H:%M') if pd.notna(voo['Voo_DataHora']) else 'N/A'
            rota = voo.get('Voo_Rota_ICAO', voo.get('Voo_Rota', 'N/A'))
            if isinstance(rota, str) and len(rota) > 25:
                rota = rota[:25] + '...'
            tipo = voo.get('Voo_Tipo', 'N/A')
            icone = 'C' if 'charter' in str(tipo).lower() else 'S'
            lista += f"  [{icone}] {hora} {rota}\n"
        
        if len(df_voos) > 8:
            lista += f"  ...e mais {len(df_voos) - 8} voos\n"
        
        return lista.strip() if lista else "Nenhum voo"
    
    def send_monthly_summary(self, df):
        """Envia resumo do mes atual com receita, custos e lucro operacional"""
        valor_col = 'Valor_Total' if 'Valor_Total' in df.columns else None
        
        df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
        df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
        
        hoje = datetime.now()
        mes_atual = hoje.month
        ano_atual = hoje.year
        dia_atual = hoje.day
        
        MESES = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril', 5: 'Maio', 6: 'Junho',
                 7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
        
        df_mes = df[(df['Voo_DataHora'].dt.month == mes_atual) & (df['Voo_DataHora'].dt.year == ano_atual)].copy()
        
        if df_mes.empty:
            return self.send_message(f"Nenhum voo em {MESES[mes_atual]} {ano_atual}")
        
        df_mes['Dia'] = df_mes['Voo_DataHora'].dt.day
        df_passado = df_mes[df_mes['Dia'] < dia_atual]
        df_futuro = df_mes[df_mes['Dia'] >= dia_atual]
        
        receita_passado = df_passado[valor_col].sum() if valor_col else 0
        receita_futuro = df_futuro[valor_col].sum() if valor_col else 0
        receita_total = df_mes[valor_col].sum() if valor_col else 0
        
        voos_charter = len(df_mes[df_mes['Voo_Tipo'].str.contains('charter', case=False, na=False)])
        voos_shuttle = len(df_mes[df_mes['Voo_Tipo'].str.contains('shuttle|cabin', case=False, na=False)])
        
        custo_var_total = 0
        horas_voos = 0
        horas_empty = 0
        ptax = 5.50
        custo_var_hora = 0
        
        if CUSTOS_AVAILABLE:
            try:
                ptax_fetcher = PTAXFetcher()
                cost_calc = CostCalculator(ptax_fetcher)
                ptax = cost_calc.get_ptax()
                custo_var_hora = cost_calc.calcular_custo_variavel_hora(ptax)
                
                calculator = EmptyLegCalculator()
                if calculator.carregar_voos_salesforce():
                    calculator.calcular_todos_empty_legs()
                    resumo_empty = calculator.get_resumo_empty_legs()
                    horas_empty = resumo_empty.get('tempo_total_horas', 0) if resumo_empty else 0
                
                horas_voos = len(df_mes) * 0.3
                custo_var_total = (horas_voos + horas_empty) * custo_var_hora
            except Exception as e:
                logging.error(f"Erro ao calcular custos: {e}")
        
        lucro_operacional = receita_total - custo_var_total
        margem_percent = (lucro_operacional / receita_total * 100) if receita_total > 0 else 0
        
        message = f"""
<b>RESUMO {MESES[mes_atual].upper()} {ano_atual}</b>

<b>VOOS</b>
Realizados (ate dia {dia_atual-1}): {len(df_passado)}
Programados (dia {dia_atual}+): {len(df_futuro)}
Total: {len(df_mes)} ({voos_charter} charter, {voos_shuttle} shuttle)

<b>RECEITA</b>
Realizada: {self.format_currency(receita_passado)}
Programada: {self.format_currency(receita_futuro)}
Total Mes: {self.format_currency(receita_total)}

<b>CUSTOS VARIAVEIS</b>
PTAX: R$ {ptax:.2f}
Custo/Hora: {self.format_currency(custo_var_hora)}
Horas Voos: {horas_voos:.1f}h + Empty Legs: {horas_empty:.1f}h
Custo Variavel Total: {self.format_currency(custo_var_total)}

<b>LUCRO OPERACIONAL</b>
Receita - Custo Variavel
{self.format_currency(receita_total)} - {self.format_currency(custo_var_total)}
= {self.format_currency(lucro_operacional)} ({margem_percent:.1f}%)

Atualizado: {datetime.now().strftime('%d/%m %H:%M')}
"""
        return self.send_message(message)
    
    def send_yearly_summary(self, df):
        """Envia resumo do ano completo"""
        valor_col = 'Valor_Total' if 'Valor_Total' in df.columns else None
        
        df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
        df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
        
        ano_atual = datetime.now().year
        mes_atual = datetime.now().month
        
        MESES = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
                 7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
        
        df_ano = df[df['Voo_DataHora'].dt.year == ano_atual].copy()
        
        if df_ano.empty:
            return self.send_message(f"Nenhum voo em {ano_atual}")
        
        df_ano['Mes'] = df_ano['Voo_DataHora'].dt.month
        
        resumo_meses = []
        for mes in sorted(df_ano['Mes'].unique()):
            df_m = df_ano[df_ano['Mes'] == mes]
            voos = len(df_m)
            receita = df_m[valor_col].sum() if valor_col else 0
            status = 'OK' if mes < mes_atual else ('ATUAL' if mes == mes_atual else 'FUTURO')
            resumo_meses.append(f"  {MESES[mes]}: {voos} voos | {self.format_currency(receita)} [{status}]")
        
        receita_total = df_ano[valor_col].sum() if valor_col else 0
        
        message = f"""
<b>RESUMO ANUAL {ano_atual}</b>

Total de Voos: {len(df_ano)}
Receita Total: {self.format_currency(receita_total)}
Meses com Operacao: {df_ano['Mes'].nunique()}

<b>POR MES</b>
{chr(10).join(resumo_meses)}

<b>POR CATEGORIA</b>
Charter: {len(df_ano[df_ano['Voo_Tipo'].str.contains('charter', case=False, na=False)])} voos
Shuttle: {len(df_ano[df_ano['Voo_Tipo'].str.contains('shuttle|cabin', case=False, na=False)])} voos

Atualizado: {datetime.now().strftime('%d/%m %H:%M')}
"""
        return self.send_message(message)
    
    def send_cost_summary(self, df):
        """Envia resumo de custos operacionais"""
        if not CUSTOS_AVAILABLE:
            return self.send_message("Modulo de custos nao disponivel")
        
        try:
            df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
            
            ptax_fetcher = PTAXFetcher()
            cost_calc = CostCalculator(ptax_fetcher)
            ptax = cost_calc.get_ptax()
            custo_var_hora = cost_calc.calcular_custo_variavel_hora(ptax)
            custo_fixo_mensal = cost_calc.calcular_custo_fixo_frota_mensal(ptax)
            
            calculator = EmptyLegCalculator()
            resumo_empty = None
            if calculator.carregar_voos_salesforce():
                calculator.calcular_todos_empty_legs()
                resumo_empty = calculator.get_resumo_empty_legs()
            
            ano_atual = datetime.now().year
            mes_atual = datetime.now().month
            
            MESES = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril', 5: 'Maio', 6: 'Junho',
                     7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
            
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            df_mes = df[(df['Voo_DataHora'].dt.month == mes_atual) & (df['Voo_DataHora'].dt.year == ano_atual)]
            df_ano = df[df['Voo_DataHora'].dt.year == ano_atual]
            
            voos_mes = len(df_mes)
            horas_voos_mes = voos_mes * 0.3
            horas_empty_mes = resumo_empty['tempo_total_horas'] if resumo_empty else 0
            custo_var_mes = (horas_voos_mes + horas_empty_mes) * custo_var_hora
            custo_total_mes = custo_fixo_mensal + custo_var_mes
            
            voos_ano = len(df_ano)
            meses_passados = mes_atual
            custo_fixo_ano = custo_fixo_mensal * meses_passados
            horas_voos_ano = voos_ano * 0.3
            custo_var_ano = (horas_voos_ano + horas_empty_mes) * custo_var_hora
            custo_total_ano = custo_fixo_ano + custo_var_ano
            
            message = f"""
<b>CUSTOS OPERACIONAIS REVO</b>

<b>PARAMETROS</b>
PTAX: R$ {ptax:.4f}
Custo/Hora: {self.format_currency(custo_var_hora)}
Fixo Mensal Frota: {self.format_currency(custo_fixo_mensal)}

<b>{MESES[mes_atual].upper()} {ano_atual}</b>
Voos SF: {voos_mes} (~{horas_voos_mes:.1f}h)
Empty Legs: {resumo_empty['total_empty_legs'] if resumo_empty else 0} ({horas_empty_mes:.1f}h)
Custo Variavel: {self.format_currency(custo_var_mes)}
Custo Total Mes: {self.format_currency(custo_total_mes)}

<b>ANO {ano_atual} (ate {MESES[mes_atual]})</b>
Voos SF: {voos_ano}
Custo Fixo ({meses_passados} meses): {self.format_currency(custo_fixo_ano)}
Custo Variavel: {self.format_currency(custo_var_ano)}
Custo Total Ano: {self.format_currency(custo_total_ano)}

Atualizado: {datetime.now().strftime('%d/%m %H:%M')}
"""
            return self.send_message(message)
            
        except Exception as e:
            logging.error(f"Erro ao calcular custos: {e}")
            return self.send_message(f"Erro ao calcular custos: {e}")
    
    def send_full_report(self, df):
        """Envia relatorio completo: resumo do dia, mes (com custos e lucro), ano e graficos"""
        self.generate_daily_summary(df)
        self.send_monthly_summary(df)
        self.send_yearly_summary(df)
        self.send_charts(df)
        return True
    
    def test_connection(self):
        """Testa a conexão com o Telegram"""
        message = f"""
🔔 <b>TESTE DE CONEXÃO</b>

✅ Bot REVO conectado com sucesso!

Este bot irá notificar sobre:
• 🚁 Novos voos criados
• ❌ Voos cancelados
• 📊 Resumo diário (08:00)
• 🌤️ Alertas meteorológicos (IFR/fechamento)

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
        return self.send_message(message)
    
    def send_weather_alert(self, alert, images: dict = None):
        """Envia alerta meteorologico com imagens opcionais"""
        icao = alert.get("icao", "????")
        name = alert.get("airport_name", icao)
        alert_type = alert.get("type", "METAR")
        category = alert.get("category", "N/A")
        
        lines = []
        
        if alert_type in ["METAR", "SPECI"]:
            if category in ["IFR", "LIFR"]:
                lines.append(f"<b>ALERTA METEO - {icao}</b>")
                lines.append(f"{name}")
                lines.append("")
                lines.append(f"Categoria: {category} (condicoes ruins)")
            else:
                lines.append(f"<b>ATENCAO METEO - {icao}</b>")
                lines.append(f"{name}")
                lines.append("")
                lines.append(f"Categoria: {category}")
            
            lines.append("")
            lines.append("<b>Situacao atual:</b>")
            for r in alert.get("reasons", []):
                lines.append(f"  - {r}")
        
        else:
            lines.append(f"<b>PREVISAO IFR - {icao}</b>")
            lines.append(f"{name}")
            lines.append("")
            
            worst = alert.get("worst_period")
            if worst:
                lines.append("<b>Periodo mais critico:</b>")
                lines.append(f"  {worst}")
                lines.append("")
            
            ifr_periods = alert.get("ifr_periods", [])
            if ifr_periods:
                lines.append("<b>Previsao detalhada:</b>")
                for period in ifr_periods[:5]:
                    if "% chance" in period:
                        lines.append(f"  {period}")
                    else:
                        lines.append(f"  {period}")
            
            lines.append("")
            lines.append("<b>O que significa:</b>")
            
            has_ts = any("trovoada" in p.lower() or "TSRA" in p for p in ifr_periods)
            has_fog = any("nevoeiro" in p.lower() or "FG" in p for p in ifr_periods)
            has_rain = any("chuva" in p.lower() or "RA" in p for p in ifr_periods)
            has_low_vis = any("Vis" in p for p in ifr_periods)
            has_low_ceil = any("Teto" in p for p in ifr_periods)
            
            if has_ts:
                lines.append("  - Trovoadas previstas (risco de raios e turbulencia)")
            if has_fog:
                lines.append("  - Nevoeiro previsto (visibilidade muito reduzida)")
            if has_rain:
                lines.append("  - Chuva forte prevista")
            if has_low_vis:
                lines.append("  - Visibilidade abaixo de 5km")
            if has_low_ceil:
                lines.append("  - Teto de nuvens baixo (abaixo de 1000ft)")
            
            lines.append("")
            lines.append("<b>Recomendacao:</b>")
            lines.append("  Monitorar condicoes antes de voos programados")
        
        lines.append("")
        lines.append(f"Atualizado: {datetime.now().strftime('%H:%M')}")
        
        result = self.send_message("\n".join(lines))
        
        if images and alert_type == "SPECI":
            self._send_weather_images(images, icao)
        
        return result
    
    def _send_weather_images(self, images: dict, context: str = ""):
        """Envia imagens meteorologicas"""
        image_captions = {
            "radar_sr": "📡 Radar Meteorologico - Sao Paulo",
            "satelite_nuvens": "🛰️ Satelite - Cobertura de Nuvens",
            "sigwx": "📋 Carta SIGWX - Tempo Significativo",
            "vento_fl100": "💨 Carta de Ventos - FL100",
        }
        
        for key, path in images.items():
            if path and os.path.exists(path):
                caption = image_captions.get(key, key)
                if context:
                    caption = f"{caption}\n{context}"
                self.send_photo(path, caption)
    
    def send_weather_summary(self, weather_data):
        """Envia resumo meteorologico completo"""
        from weather_monitor import AIRPORT_INFO
        
        lines = ["<b>🌤️ METEOROLOGIA SP - AEROPORTOS</b>"]
        lines.append(f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
        
        for metar in weather_data.get("metars", []):
            icao = metar.get("icao", "????")
            airport = AIRPORT_INFO.get(icao, {})
            name = airport.get("name", icao)
            cat = metar.get("flight_category", "N/A")
            cat_emoji = {"VFR": "🟢", "MVFR": "🔵", "IFR": "🔴", "LIFR": "🟣"}.get(cat, "⚪")
            
            lines.append(f"<b>{icao} - {name}</b> {cat_emoji} {cat}")
            lines.append(f"<code>{metar.get('raw', '')}</code>")
            
            details = []
            if metar.get("visibility_str"):
                details.append(f"Vis: {metar['visibility_str']}")
            if metar.get("ceiling_ft"):
                details.append(f"Teto: {metar['ceiling_ft']}ft")
            if metar.get("wind_speed"):
                wind = f"{metar.get('wind_dir', 'VRB')}/{metar['wind_speed']}kt"
                if metar.get("wind_gust"):
                    wind += f" G{metar['wind_gust']}"
                details.append(f"Vento: {wind}")
            if metar.get("weather_decoded"):
                details.append(f"Tempo: {', '.join(metar['weather_decoded'])}")
            
            if details:
                lines.append("  " + " | ".join(details))
            
            if metar.get("is_ifr_closed"):
                lines.append(f"  ⚠️ {', '.join(metar['closure_reasons'])}")
            
            lines.append("")
        
        lines.append("<b>PREVISOES (TAF)</b>")
        for taf in weather_data.get("tafs", []):
            icao = taf.get("icao", "????")
            airport = AIRPORT_INFO.get(icao, {})
            name = airport.get("name", icao)
            
            if taf.get("has_ifr_forecast"):
                lines.append(f"[!] {icao}: IFR previsto")
                
                worst = taf.get("worst_period")
                if worst:
                    lines.append(f"    PIOR: {worst}")
                
                for period in taf.get("ifr_periods", [])[:4]:
                    lines.append(f"    - {period}")
            else:
                lines.append(f"[OK] {icao}: Sem IFR previsto")
        
        return self.send_message("\n".join(lines))
    
    def send_morning_briefing(self, voos_hoje, voos_amanha, weather_data, voos_depois_amanha=None, voos_proximos_dias=None):
        """
        Envia briefing matinal completo com voos e meteorologia
        Cruza informacoes para alertar sobre possiveis problemas
        """
        from weather_monitor import AIRPORT_INFO
        
        lines = ["<b>☀️ BOM DIA! BRIEFING REVO</b>"]
        lines.append(f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
        
        weather_by_icao = {}
        for metar in weather_data.get("metars", []):
            weather_by_icao[metar.get("icao")] = metar
        
        taf_alerts = {}
        for taf in weather_data.get("tafs", []):
            if taf.get("has_ifr_forecast"):
                taf_alerts[taf.get("icao")] = taf.get("ifr_periods", [])
        
        def check_flight_weather(voo, weather_by_icao, taf_alerts):
            """Verifica se voo tem problemas meteorologicos"""
            problems = []
            rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or voo.get('Voo_Rota_ICAO') or voo.get('Voo_Rota', '')
            
            icaos = []
            for part in str(rota).replace('>', ' ').replace('-', ' ').split():
                part = part.strip().upper()
                if len(part) == 4 and part.isalpha():
                    icaos.append(part)
            
            for icao in icaos:
                metar = weather_by_icao.get(icao)
                if metar:
                    cat = metar.get("flight_category", "VFR")
                    if cat in ["IFR", "LIFR"]:
                        problems.append(f"{icao}: {cat}")
                    if metar.get("is_ifr_closed"):
                        for reason in metar.get("closure_reasons", [])[:2]:
                            problems.append(f"{icao}: {reason}")
                
                if icao in taf_alerts:
                    problems.append(f"{icao}: IFR previsto no TAF")
            
            return problems
        
        if voos_hoje:
            lines.append(f"<b>🚁 VOOS HOJE ({len(voos_hoje)})</b>")
            lines.append("")
            
            for voo in voos_hoje:
                dt_voo = voo.get('DataHoraVoo__c') or voo.get('Voo_DataHora', '')
                hora = '--:--'
                if dt_voo:
                    try:
                        if isinstance(dt_voo, str):
                            dt = datetime.fromisoformat(dt_voo.replace('Z', '+00:00'))
                        else:
                            dt = dt_voo
                        dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                        hora = dt_local.strftime('%H:%M')
                    except:
                        pass
                
                prefixo = _extrair_prefixo(voo)
                
                rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or voo.get('Voo_Rota_ICAO') or ''
                rota = str(rota).replace('<', '').replace('&', '')
                rota_parts = rota.replace('>', '-').split('-')
                if len(rota_parts) >= 2:
                    rota_short = f"{rota_parts[0].strip()}-{rota_parts[-1].strip()}"
                else:
                    rota_short = rota[:15] if rota else '-'
                
                pax = int(voo.get('ContadorPassageiros__c') or voo.get('Voo_Contador_Passageiros') or 0)
                
                host = voo.get('ResponsavelpelaoperacaoTerrestre__c') or ''
                host = str(host).replace('<', '').replace('>', '').replace('&', '').strip()
                host_str = f" | Host: {host}" if host else ""
                
                problems = check_flight_weather(voo, weather_by_icao, taf_alerts)
                
                if problems:
                    emoji = "⚠️"
                    status_meteo = f" ({problems[0]})"
                else:
                    emoji = "✅"
                    status_meteo = ""
                
                lines.append(f"{emoji} {hora} <b>{prefixo}</b> | {rota_short} | {pax}pax{host_str}{status_meteo}")
            
            lines.append("")
        else:
            lines.append("<b>🚁 VOOS HOJE</b>")
            lines.append("Nenhum voo programado")
            lines.append("")
        
        if voos_amanha:
            lines.append(f"<b>📆 VOOS AMANHA ({len(voos_amanha)})</b>")
            lines.append("")
            
            for voo in voos_amanha[:5]:
                dt_voo = voo.get('DataHoraVoo__c') or voo.get('Voo_DataHora', '')
                hora = '--:--'
                if dt_voo:
                    try:
                        if isinstance(dt_voo, str):
                            dt = datetime.fromisoformat(dt_voo.replace('Z', '+00:00'))
                        else:
                            dt = dt_voo
                        dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                        hora = dt_local.strftime('%H:%M')
                    except:
                        pass
                
                prefixo = _extrair_prefixo(voo)
                
                rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or voo.get('Voo_Rota_ICAO') or ''
                rota = str(rota).replace('<', '').replace('&', '')
                rota_parts = rota.replace('>', '-').split('-')
                if len(rota_parts) >= 2:
                    rota_short = f"{rota_parts[0].strip()}-{rota_parts[-1].strip()}"
                else:
                    rota_short = rota[:15] if rota else '-'
                
                pax = int(voo.get('ContadorPassageiros__c') or voo.get('Voo_Contador_Passageiros') or 0)
                
                host = voo.get('ResponsavelpelaoperacaoTerrestre__c') or ''
                host = str(host).replace('<', '').replace('>', '').replace('&', '').strip()
                host_str = f" | Host: {host}" if host else ""
                
                problems = check_flight_weather(voo, weather_by_icao, taf_alerts)
                if problems:
                    emoji = "⚠️"
                else:
                    emoji = "📌"
                
                lines.append(f"{emoji} {hora} <b>{prefixo}</b> | {rota_short} | {pax}pax{host_str}")
            
            if len(voos_amanha) > 5:
                lines.append(f"   ... e mais {len(voos_amanha) - 5} voos")

            lines.append("")

        if voos_depois_amanha:
            depois_amanha_date = (datetime.now() + timedelta(days=2)).strftime('%d/%m')
            lines.append(f"<b>📆 DEPOIS DE AMANHA - {depois_amanha_date} ({len(voos_depois_amanha)})</b>")
            lines.append("")

            for voo in voos_depois_amanha[:5]:
                dt_voo = voo.get('DataHoraVoo__c') or voo.get('Voo_DataHora', '')
                hora = '--:--'
                if dt_voo:
                    try:
                        if isinstance(dt_voo, str):
                            dt = datetime.fromisoformat(dt_voo.replace('Z', '+00:00'))
                        else:
                            dt = dt_voo
                        dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                        hora = dt_local.strftime('%H:%M')
                    except:
                        pass

                prefixo = _extrair_prefixo(voo)

                rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or voo.get('Voo_Rota_ICAO') or ''
                rota = str(rota).replace('<', '').replace('&', '')
                rota_parts = rota.replace('>', '-').split('-')
                if len(rota_parts) >= 2:
                    rota_short = f"{rota_parts[0].strip()}-{rota_parts[-1].strip()}"
                else:
                    rota_short = rota[:15] if rota else '-'

                pax = int(voo.get('ContadorPassageiros__c') or voo.get('Voo_Contador_Passageiros') or 0)

                host = voo.get('ResponsavelpelaoperacaoTerrestre__c') or ''
                host = str(host).replace('<', '').replace('>', '').replace('&', '').strip()
                host_str = f" | Host: {host}" if host else ""

                problems = check_flight_weather(voo, weather_by_icao, taf_alerts)
                if problems:
                    emoji = "⚠️"
                else:
                    emoji = "📌"

                lines.append(f"{emoji} {hora} <b>{prefixo}</b> | {rota_short} | {pax}pax{host_str}")

            if len(voos_depois_amanha) > 5:
                lines.append(f"   ... e mais {len(voos_depois_amanha) - 5} voos")

            lines.append("")

        if voos_proximos_dias:
            for dia_info in voos_proximos_dias:
                label = dia_info['label']
                dia_voos = dia_info['voos']
                lines.append(f"<b>📆 {label} ({len(dia_voos)})</b>")
                lines.append("")

                for voo in dia_voos[:3]:
                    dt_voo = voo.get('DataHoraVoo__c') or voo.get('Voo_DataHora', '')
                    hora = '--:--'
                    if dt_voo:
                        try:
                            if isinstance(dt_voo, str):
                                dt = datetime.fromisoformat(dt_voo.replace('Z', '+00:00'))
                            else:
                                dt = dt_voo
                            dt_local = dt - timedelta(hours=3) if dt.tzinfo else dt
                            hora = dt_local.strftime('%H:%M')
                        except:
                            pass

                    prefixo = _extrair_prefixo(voo)

                    rota = voo.get('RotaAbreviada__c') or voo.get('Rota__c') or voo.get('Voo_Rota_ICAO') or ''
                    rota = str(rota).replace('<', '').replace('&', '')
                    rota_parts = rota.replace('>', '-').split('-')
                    if len(rota_parts) >= 2:
                        rota_short = f"{rota_parts[0].strip()}-{rota_parts[-1].strip()}"
                    else:
                        rota_short = rota[:15] if rota else '-'

                    pax = int(voo.get('ContadorPassageiros__c') or voo.get('Voo_Contador_Passageiros') or 0)

                    lines.append(f"📌 {hora} <b>{prefixo}</b> | {rota_short} | {pax}pax")

                if len(dia_voos) > 3:
                    lines.append(f"   ... e mais {len(dia_voos) - 3} voos")

                lines.append("")

        lines.append("<b>METEOROLOGIA SP</b>")
        lines.append("")
        
        for metar in weather_data.get("metars", []):
            icao = metar.get("icao", "????")
            airport = AIRPORT_INFO.get(icao, {})
            name = airport.get("name", icao)
            cat = metar.get("flight_category", "N/A")
            cat_emoji = {"VFR": "V", "MVFR": "M", "IFR": "I", "LIFR": "L"}.get(cat, "?")
            
            vis = metar.get("visibility_str", "-")
            ceiling = metar.get("ceiling_ft")
            ceiling_str = f"{ceiling}ft" if ceiling else "ilimitado"
            
            lines.append(f"[{cat_emoji}] {icao}: {cat} | Vis {vis} | Teto {ceiling_str}")
            
            if metar.get("is_ifr_closed"):
                reasons = metar.get('closure_reasons', [])[:2]
                reasons_clean = [str(r).replace('<', '').replace('>', '') for r in reasons]
                lines.append(f"    ALERTA: {'; '.join(reasons_clean)}")
        
        lines.append("")
        
        has_alerts = any(m.get("is_ifr_closed") for m in weather_data.get("metars", []))
        has_taf_alerts = any(t.get("has_ifr_forecast") for t in weather_data.get("tafs", []))
        
        if has_alerts or has_taf_alerts:
            lines.append("⚠️ <b>ATENCAO: Condicoes meteorologicas requerem monitoramento!</b>")
        else:
            lines.append("✅ <b>Condicoes meteorologicas favoraveis para operacao</b>")
        
        result = self.send_message("\n".join(lines))
        
        try:
            chart_paths = self.generate_helicopter_routes_chart(voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias)
            if chart_paths:
                for chart_path in chart_paths:
                    if 'hoje' in chart_path:
                        self.send_photo(chart_path, "Rotas de Hoje")
                    elif 'depois' in chart_path:
                        self.send_photo(chart_path, "Rotas de Depois de Amanha")
                    elif 'amanha' in chart_path:
                        self.send_photo(chart_path, "Rotas de Amanha")
                    else:
                        self.send_photo(chart_path, f"Rotas Proximos Dias")

            map_paths = self.generate_routes_map(voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias)
            if map_paths:
                for map_path in map_paths:
                    if 'geral' in map_path:
                        self.send_photo(map_path, "Mapa Geral")
                    else:
                        self.send_photo(map_path, "Mapa SP")
        except Exception as e:
            logging.error(f"Erro ao gerar diagramas: {e}")
        
        return result


def setup_telegram():
    """Guia de configuração do Telegram"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║          CONFIGURAÇÃO DO BOT TELEGRAM - REVO                 ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  PASSO 1: Criar o Bot                                        ║
║  ─────────────────────                                       ║
║  1. Abra o Telegram e busque: @BotFather                     ║
║  2. Envie: /newbot                                           ║
║  3. Escolha um nome: "REVO Notificações"                     ║
║  4. Escolha um username: "revo_voos_bot"                     ║
║  5. Copie o TOKEN fornecido                                  ║
║                                                              ║
║  PASSO 2: Obter seu Chat ID                                  ║
║  ──────────────────────────                                  ║
║  1. Busque: @userinfobot no Telegram                         ║
║  2. Envie qualquer mensagem                                  ║
║  3. Copie o "Id" que ele retornar                            ║
║                                                              ║
║  PASSO 3: Configurar o .env                                  ║
║  ──────────────────────────                                  ║
║  Adicione no arquivo .env:                                   ║
║                                                              ║
║  TELEGRAM_BOT_TOKEN=seu_token_aqui                           ║
║  TELEGRAM_CHAT_ID=seu_chat_id_aqui                           ║
║                                                              ║
║  PASSO 4: Testar                                             ║
║  ─────────────────                                           ║
║  Execute: python telegram_notifier.py --test                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


def get_voos_salesforce(dias=7):
    """Busca voos do Salesforce para os proximos dias (padrao: 7 dias).

    Retorna: (voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias)
      - voos_hoje: lista de voos de hoje
      - voos_amanha: lista de voos de amanha
      - voos_depois_amanha: lista de voos do dia +2
      - voos_proximos_dias: lista de dicts [{date, label, voos}] para dias +3 ate +6
    """
    try:
        from simple_salesforce import Salesforce
        from dotenv import load_dotenv
        load_dotenv()

        sf = Salesforce(
            username=os.getenv('SF_USERNAME'),
            password=os.getenv('SF_PASSWORD'),
            security_token=os.getenv('SF_SECURITY_TOKEN'),
            domain=os.getenv('SF_DOMAIN', 'login')
        )

        hoje = datetime.now().strftime('%Y-%m-%d')
        ultimo_dia = (datetime.now() + timedelta(days=dias - 1)).strftime('%Y-%m-%d')

        query = f"""
        SELECT
            Id, Name, Tipo__c, Status__c, DataHoraVoo__c,
            Rota__c, RotaAbreviada__c, Prefixo__c, Prefixo__r.Name, PrefixoTexto__c,
            ContadorPassageiros__c, ReceitaVoo__c,
            ResponsavelpelaoperacaoTerrestre__c, Hostsembarque__c, Hostsdesembarque__c
        FROM Voo__c
        WHERE DataHoraVoo__c >= {hoje}T00:00:00Z
        AND DataHoraVoo__c <= {ultimo_dia}T23:59:59Z
        AND (Status__c LIKE '%Confirm%' OR Status__c LIKE '%Reserv%' OR Status__c LIKE '%Pago%')
        ORDER BY DataHoraVoo__c ASC
        """

        result = sf.query_all(query)
        voos = result.get('records', [])

        DIAS_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sab', 'Dom']

        voos_hoje = []
        voos_amanha = []
        voos_depois_amanha = []
        # Dias +3 a +6 (4 dias adicionais)
        voos_por_dia_extra = {}
        for d in range(3, dias):
            target_date = (datetime.now() + timedelta(days=d)).date()
            dia_semana = DIAS_SEMANA[target_date.weekday()]
            voos_por_dia_extra[target_date] = {
                'date': target_date,
                'label': f"{dia_semana} {target_date.strftime('%d/%m')}",
                'voos': []
            }

        for voo in voos:
            dt_voo = voo.get('DataHoraVoo__c', '')
            if dt_voo:
                try:
                    dt = datetime.fromisoformat(dt_voo.replace('Z', '+00:00'))
                    dt_local = dt - timedelta(hours=3)
                    voo_date = dt_local.date()
                    if voo_date == datetime.now().date():
                        voos_hoje.append(voo)
                    elif voo_date == (datetime.now() + timedelta(days=1)).date():
                        voos_amanha.append(voo)
                    elif voo_date == (datetime.now() + timedelta(days=2)).date():
                        voos_depois_amanha.append(voo)
                    elif voo_date in voos_por_dia_extra:
                        voos_por_dia_extra[voo_date]['voos'].append(voo)
                except:
                    pass

        voos_proximos_dias = [v for v in voos_por_dia_extra.values() if v['voos']]
        voos_proximos_dias.sort(key=lambda x: x['date'])

        return voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias

    except Exception as e:
        logging.error(f"Erro ao buscar voos do Salesforce: {e}")
        return [], [], [], []


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Notificacoes Telegram - REVO')
    parser.add_argument('--setup', action='store_true', help='Mostra guia de configuracao')
    parser.add_argument('--test', action='store_true', help='Testa conexao com Telegram')
    parser.add_argument('--summary', action='store_true', help='Envia resumo diario')
    parser.add_argument('--month', action='store_true', help='Envia resumo do mes atual')
    parser.add_argument('--year', action='store_true', help='Envia resumo do ano')
    parser.add_argument('--costs', action='store_true', help='Envia resumo de custos')
    parser.add_argument('--charts', action='store_true', help='Envia graficos (receita e mapa)')
    parser.add_argument('--full', action='store_true', help='Envia relatorio completo (tudo)')
    parser.add_argument('--weather', action='store_true', help='Envia resumo meteorologico (METAR/TAF)')
    parser.add_argument('--weather-alerts', action='store_true', help='Envia apenas alertas meteorologicos (IFR/fechamento)')
    parser.add_argument('--briefing', action='store_true', help='Envia briefing matinal (voos + meteorologia)')
    parser.add_argument('--csv', type=str, default='dados_reservas.csv', help='Arquivo CSV de dados')
    
    args = parser.parse_args()
    
    if args.setup:
        setup_telegram()
        return
    
    notifier = TelegramNotifier()
    
    if args.test:
        if notifier.test_connection():
            print("Conexao com Telegram OK!")
        else:
            print("Falha na conexao. Verifique as credenciais.")
        return
    
    if args.briefing:
        from weather_monitor import WeatherMonitor
        
        print("Buscando voos do Salesforce...")
        voos_hoje, voos_amanha, voos_depois_amanha, voos_proximos_dias = get_voos_salesforce()
        total_proximos = sum(len(d['voos']) for d in voos_proximos_dias)
        print(f"Encontrados: {len(voos_hoje)} voos hoje, {len(voos_amanha)} voos amanha, {len(voos_depois_amanha)} depois de amanha, {total_proximos} proximos dias")

        print("Buscando meteorologia...")
        weather_mon = WeatherMonitor()
        weather_data = weather_mon.check_weather()

        print("Enviando briefing...")
        if notifier.send_morning_briefing(voos_hoje, voos_amanha, weather_data, voos_depois_amanha, voos_proximos_dias):
            print("Briefing matinal enviado!")
        else:
            print("Falha ao enviar briefing")
        return
    
    if args.weather or args.weather_alerts:
        from weather_monitor import WeatherMonitor
        weather_mon = WeatherMonitor()
        weather_data = weather_mon.check_weather()
        
        if args.weather_alerts:
            if weather_data["alerts"]:
                for alert in weather_data["alerts"]:
                    notifier.send_weather_alert(alert)
                print(f"{len(weather_data['alerts'])} alertas meteorologicos enviados!")
            else:
                print("Nenhum alerta meteorologico no momento")
        else:
            if notifier.send_weather_summary(weather_data):
                print("Resumo meteorologico enviado!")
            else:
                print("Falha ao enviar resumo meteorologico")
        return
    
    if not os.path.exists(args.csv):
        print(f"Arquivo nao encontrado: {args.csv}")
        print("   Execute primeiro: python salesforce_extractor.py --api --ano 2026")
        return
    
    df = pd.read_csv(args.csv, encoding='utf-8-sig')
    df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
    
    if args.summary:
        if notifier.generate_daily_summary(df):
            print("Resumo diario enviado!")
        else:
            print("Falha ao enviar resumo")
    
    if args.month:
        if notifier.send_monthly_summary(df):
            print("Resumo mensal enviado!")
        else:
            print("Falha ao enviar resumo mensal")
    
    if args.year:
        if notifier.send_yearly_summary(df):
            print("Resumo anual enviado!")
        else:
            print("Falha ao enviar resumo anual")
    
    if args.costs:
        if notifier.send_cost_summary(df):
            print("Resumo de custos enviado!")
        else:
            print("Falha ao enviar custos")
    
    if args.charts:
        if notifier.send_charts(df):
            print("Graficos enviados!")
        else:
            print("Falha ao enviar graficos")
    
    if args.full:
        if notifier.send_full_report(df):
            print("Relatorio completo enviado!")
        else:
            print("Falha ao enviar relatorio")


if __name__ == "__main__":
    main()
