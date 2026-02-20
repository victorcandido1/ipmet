"""
Modulo de Imagens Meteorologicas - REVO
Fontes de ALTA QUALIDADE (gratuitas, sem API key):
- IPMET/UNESP: Radar GIF animado (Bauru - cobre SP)
- NOAA GOES-16: Satelite America do Sul (alta resolucao)
- Windy: Radar meteorologico via screenshot (Selenium)
"""

import os
import requests
import logging
import base64
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL nao instalado - pip install Pillow")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

SP_CENTER = {"lat": -23.55, "lon": -46.63}

NOAA_GOES_URLS = {
    "geocolor": "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/ssa/GEOCOLOR/latest.jpg",
    "ir_band13": "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/ssa/13/latest.jpg",
    "vapor": "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/ssa/09/latest.jpg",
}

IPMET_URL = "https://www.ipmetradar.com.br/"


class WeatherImagesClient:
    def __init__(self):
        self.images_dir = 'weather_images'
        self.max_telegram_size = 1920
        
        if not os.path.exists(self.images_dir):
            os.makedirs(self.images_dir)
    
    def is_configured(self) -> bool:
        return True
    
    def _resize_image(self, image_path: str, max_size: int = 1920) -> str:
        """Redimensiona imagem para tamanho adequado ao Telegram"""
        if not PIL_AVAILABLE:
            return image_path
        
        try:
            img = Image.open(image_path)
            
            if max(img.size) <= max_size:
                return image_path
            
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            resized_path = image_path.replace('.jpg', '_resized.jpg').replace('.png', '_resized.png')
            
            if image_path.endswith('.jpg') or image_path.endswith('.jpeg'):
                img_resized.save(resized_path, 'JPEG', quality=90)
            else:
                img_resized.save(resized_path, 'PNG')
            
            logging.info(f"Imagem redimensionada: {img.size} -> {new_size}")
            return resized_path
            
        except Exception as e:
            logging.error(f"Erro ao redimensionar: {e}")
            return image_path
    
    def _download_image(self, url: str, filename: str, resize: bool = True) -> Optional[str]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, timeout=90, headers=headers)
            response.raise_for_status()
            
            if len(response.content) < 1000:
                logging.warning(f"Imagem muito pequena: {url}")
                return None
            
            filepath = os.path.join(self.images_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            size_kb = len(response.content) / 1024
            logging.info(f"Imagem salva: {filepath} ({size_kb:.0f} KB)")
            
            if resize and len(response.content) > 500000:
                filepath = self._resize_image(filepath, self.max_telegram_size)
            
            return filepath
            
        except Exception as e:
            logging.error(f"Erro ao baixar imagem {url}: {e}")
            return None
    
    def get_noaa_satellite(self, tipo: str = "geocolor") -> Optional[str]:
        """
        Busca imagem de satelite GOES-16 do NOAA (ALTA QUALIDADE)
        
        Args:
            tipo: 'geocolor' (colorida), 'ir_band13' (infravermelho), 'vapor' (vapor d'agua)
        """
        url = NOAA_GOES_URLS.get(tipo)
        if not url:
            logging.error(f"Tipo de satelite invalido: {tipo}")
            return None
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        filename = f"satelite_noaa_{tipo}_{timestamp}.jpg"
        
        logging.info(f"Baixando satelite NOAA ({tipo})...")
        return self._download_image(url, filename, resize=True)
    
    def get_ipmet_gif(self, tipo: str = "radar") -> Optional[str]:
        """
        Busca GIF animado do IPMET/UNESP via Selenium
        
        Args:
            tipo: 'radar' (ppi.gif) ou 'satelite' (sat.gif)
        
        Retorna o caminho do arquivo GIF animado
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time
        except ImportError:
            logging.error("Selenium nao instalado - pip install selenium")
            return None
        
        gif_patterns = {
            "radar": "ppi.gif",
            "satelite": "sat.gif",
        }
        
        pattern = gif_patterns.get(tipo, "ppi.gif")
        
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            driver = webdriver.Chrome(options=chrome_options)
            
            try:
                logging.info(f"Acessando IPMET para pegar {tipo} animado...")
                driver.get(IPMET_URL)
                time.sleep(5)
                
                imgs = driver.find_elements(By.TAG_NAME, "img")
                gif_url = None
                
                for img in imgs:
                    src = img.get_attribute("src") or ""
                    if pattern in src:
                        gif_url = src
                        break
                
                if not gif_url:
                    logging.warning(f"GIF {tipo} IPMET nao encontrado")
                    return None
                
                fetch_script = """
                return new Promise((resolve, reject) => {
                    fetch(arguments[0], {
                        credentials: 'include',
                        headers: {'Accept': 'image/gif,image/*'}
                    })
                    .then(response => response.arrayBuffer())
                    .then(buffer => {
                        const bytes = new Uint8Array(buffer);
                        let binary = '';
                        for (let i = 0; i < bytes.byteLength; i++) {
                            binary += String.fromCharCode(bytes[i]);
                        }
                        resolve(btoa(binary));
                    })
                    .catch(reject);
                });
                """
                
                result = driver.execute_script(fetch_script, gif_url)
                gif_data = base64.b64decode(result)
                
                if gif_data[:3] != b'GIF':
                    logging.warning(f"Dados do IPMET {tipo} nao sao GIF valido")
                    return None
                
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
                filename = f"{tipo}_ipmet_{timestamp}.gif"
                filepath = os.path.join(self.images_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(gif_data)
                
                size_kb = len(gif_data) / 1024
                logging.info(f"IPMET {tipo} GIF animado: {filepath} ({size_kb:.0f} KB)")
                
                if PIL_AVAILABLE:
                    img = Image.open(filepath)
                    n_frames = getattr(img, 'n_frames', 1)
                    logging.info(f"  Dimensoes: {img.size}, Frames: {n_frames}")
                
                return filepath
                
            finally:
                driver.quit()
                
        except Exception as e:
            logging.error(f"Erro ao buscar {tipo} IPMET: {e}")
            return None
    
    def get_ipmet_radar_gif(self) -> Optional[str]:
        """Busca GIF animado do radar IPMET/UNESP"""
        return self.get_ipmet_gif("radar")
    
    def get_ipmet_satelite_gif(self) -> Optional[str]:
        """Busca GIF animado do satelite IPMET/UNESP"""
        return self.get_ipmet_gif("satelite")
    
    def get_windy_screenshot(self, layer: str = "radar") -> Optional[str]:
        """
        Captura screenshot do Windy usando Selenium (ALTA QUALIDADE)
        Focado na cidade de Sao Paulo e regiao metropolitana
        
        Args:
            layer: 'radar', 'satellite', 'clouds', 'wind', 'rain'
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            import time
        except ImportError:
            logging.error("Selenium nao instalado - pip install selenium")
            return None
        
        try:
            lat = -23.55
            lon = -46.63
            zoom = 9
            
            url = f"https://embed.windy.com/embed2.html?lat={lat}&lon={lon}&detailLat={lat}&detailLon={lon}&width=1200&height=900&zoom={zoom}&level=surface&overlay={layer}&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1"
            
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1200,900")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--hide-scrollbars")
            
            driver = webdriver.Chrome(options=chrome_options)
            
            try:
                logging.info(f"Capturando Windy ({layer}) - Foco SP...")
                driver.get(url)
                
                time.sleep(8)
                
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
                filename = f"windy_{layer}_{timestamp}.png"
                filepath = os.path.join(self.images_dir, filename)
                
                driver.save_screenshot(filepath)
                
                if PIL_AVAILABLE:
                    img = Image.open(filepath)
                    img = img.crop((0, 0, 1200, 850))
                    img.save(filepath)
                
                size_kb = os.path.getsize(filepath) / 1024
                logging.info(f"Windy screenshot salvo: {filepath} ({size_kb:.0f} KB)")
                return filepath
                
            finally:
                driver.quit()
                
        except Exception as e:
            logging.error(f"Erro ao capturar Windy: {e}")
            return None
    
    def get_radar_image(self) -> Optional[str]:
        """Busca imagem de radar (IPMET GIF ou Windy fallback)"""
        img = self.get_ipmet_radar_gif()
        if not img:
            logging.info("IPMET indisponivel, usando Windy...")
            img = self.get_windy_screenshot("radar")
        return img
    
    def get_satellite_image(self) -> Optional[str]:
        """Busca melhor imagem de satelite disponivel (NOAA GOES-16)"""
        img = self.get_noaa_satellite("geocolor")
        if not img:
            img = self.get_windy_screenshot("satellite")
        return img
    
    def get_clouds_image(self) -> Optional[str]:
        """Busca imagem de nuvens infravermelho (NOAA)"""
        return self.get_noaa_satellite("ir_band13")
    
    def get_speci_package(self) -> Dict[str, Optional[str]]:
        """Pacote rapido para SPECI (radar + satelite)"""
        images = {}
        
        logging.info("Pacote SPECI...")
        images["radar"] = self.get_ipmet_radar_gif()
        if not images["radar"]:
            images["radar"] = self.get_windy_screenshot("radar")
        images["satelite"] = self.get_noaa_satellite("geocolor")
        
        return images
    
    def get_redemet_sigwx(self, tipo: str = "siginf") -> Optional[str]:
        """
        Baixa carta SIGWX do REDEMET diretamente (sem Selenium)
        
        Args:
            tipo: Tipo de carta SIGWX
                - siginf: SIGWX Inferior (SUP-FL250) - MELHOR PARA HELICOPTEROS
                - sigam: SIGWX Americas (FL250-FL630)
                - sigcob: SIGWX Cobertura
        """
        try:
            now = datetime.now(timezone.utc)
            
            rodadas = [0, 6, 12, 18]
            hora_atual = now.hour
            rodada = max([r for r in rodadas if r <= hora_atual], default=0)
            
            base_url = "https://redemet.decea.mil.br"
            path = f"/old/sigwx/{now.year}/{now.month:02d}/{now.day:02d}/{tipo}{rodada:02d}.gif"
            url = base_url + path
            
            logging.info(f"Baixando SIGWX {tipo} do REDEMET...")
            logging.info(f"URL: {url}")
            
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code != 200 or len(response.content) < 1000:
                yesterday = now - timedelta(days=1)
                path = f"/old/sigwx/{yesterday.year}/{yesterday.month:02d}/{yesterday.day:02d}/{tipo}12.gif"
                url = base_url + path
                logging.info(f"Tentando rodada anterior: {url}")
                response = requests.get(url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
            
            if response.status_code == 200 and len(response.content) > 1000:
                timestamp = now.strftime("%Y%m%d_%H%M")
                filename = f"sigwx_{tipo}_{timestamp}.gif"
                filepath = os.path.join(self.images_dir, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                size_kb = len(response.content) / 1024
                logging.info(f"SIGWX {tipo} salvo: {filepath} ({size_kb:.0f} KB)")
                return filepath
            else:
                logging.warning(f"SIGWX {tipo} nao disponivel: status={response.status_code}")
                return None
                
        except Exception as e:
            logging.error(f"Erro ao baixar SIGWX REDEMET: {e}")
            return None

    def get_redemet_indice_k(self) -> Optional[str]:
        """Baixa carta de Indice K (potencial de tempestades) do REDEMET"""
        try:
            now = datetime.now(timezone.utc)
            base_url = "https://redemet.decea.mil.br"
            
            logging.info("Baixando Indice K do REDEMET...")
            for rodada in [0, 6, 12, 18]:
                for day_offset in [0, 1]:
                    target_day = now - timedelta(days=day_offset)
                    path = f"/old/sigwx/{target_day.year}/{target_day.month:02d}/{target_day.day:02d}/auxik-{rodada:02d}Z.gif"
                    url = base_url + path
                    
                    response = requests.get(url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    if response.status_code == 200 and len(response.content) > 1000:
                        timestamp = now.strftime("%Y%m%d_%H%M")
                        filename = f"indice_k_{timestamp}.gif"
                        filepath = os.path.join(self.images_dir, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(response.content)
                        
                        logging.info(f"Indice K salvo: {filepath}")
                        return filepath
            
            logging.warning("Indice K nao disponivel")
            return None
        except Exception as e:
            logging.error(f"Erro ao baixar Indice K: {e}")
            return None

    def get_redemet_ventos_850(self) -> Optional[str]:
        """Baixa carta de ventos em 850 hPa (~1500m) do REDEMET"""
        try:
            now = datetime.now(timezone.utc)
            base_url = "https://redemet.decea.mil.br"
            
            logging.info("Baixando Ventos 850 hPa do REDEMET...")
            for rodada in [0, 6, 12, 18]:
                for day_offset in [0, 1]:
                    target_day = now - timedelta(days=day_offset)
                    path = f"/old/sigwx/{target_day.year}/{target_day.month:02d}/{target_day.day:02d}/aux850-{rodada:02d}Z.gif"
                    url = base_url + path
                    
                    response = requests.get(url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    if response.status_code == 200 and len(response.content) > 1000:
                        timestamp = now.strftime("%Y%m%d_%H%M")
                        filename = f"ventos_850hpa_{timestamp}.gif"
                        filepath = os.path.join(self.images_dir, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(response.content)
                        
                        logging.info(f"Ventos 850 hPa salvo: {filepath}")
                        return filepath
            
            logging.warning("Ventos 850 hPa nao disponivel")
            return None
        except Exception as e:
            logging.error(f"Erro ao baixar Ventos 850: {e}")
            return None

    def get_airport_webcam(self, airport: str = "SBGR") -> Optional[str]:
        """
        Captura screenshot de webcam de aeroporto
        
        Args:
            airport: SBGR (Guarulhos), SBSP (Congonhas), HELIPARK
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time
        except ImportError:
            logging.error("Selenium nao instalado")
            return None
        
        webcam_urls = {
            "SBGR": "https://www.youtube.com/watch?v=VkP9X7iz9Q",
            "SBSP": "https://www.youtube.com/watch?v=U3zQ1MQOiEg",
            "HELIPARK": "https://player.radiosnaweb.com/camera/helipark-sul",
        }
        
        if airport not in webcam_urls:
            logging.warning(f"Webcam nao disponivel para {airport}")
            return None
        
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--mute-audio")
            
            driver = webdriver.Chrome(options=chrome_options)
            
            try:
                logging.info(f"Capturando webcam {airport}...")
                driver.get(webcam_urls[airport])
                time.sleep(8)
                
                try:
                    play_btn = driver.find_element(By.CSS_SELECTOR, 'button.ytp-large-play-button, .ytp-cued-thumbnail-overlay')
                    play_btn.click()
                    time.sleep(3)
                except:
                    pass
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                filename = f"webcam_{airport}_{timestamp}.png"
                filepath = os.path.join(self.images_dir, filename)
                
                driver.save_screenshot(filepath)
                
                size_kb = os.path.getsize(filepath) / 1024
                logging.info(f"Webcam {airport} salvo: {filepath} ({size_kb:.0f} KB)")
                return filepath
                
            finally:
                driver.quit()
                
        except Exception as e:
            logging.error(f"Erro ao capturar webcam {airport}: {e}")
            return None

    def get_weather_update_package(self) -> Dict[str, Optional[str]]:
        """
        Pacote completo para atualizacoes programadas (09h, 12h, 15h, 17h)
        IPMET + NOAA + Windy + SIGWX + Indice K + Ventos + Webcams
        """
        images = {}
        
        logging.info("=" * 50)
        logging.info("PACOTE METEOROLOGICO COMPLETO")
        logging.info("=" * 50)
        
        logging.info("")
        logging.info("1/5 - Radar IPMET (GIF animado)...")
        images["radar_gif"] = self.get_ipmet_radar_gif()
        
        logging.info("")
        logging.info("2/5 - Satelite IPMET (GIF animado)...")
        images["satelite_gif"] = self.get_ipmet_satelite_gif()
        
        logging.info("")
        logging.info("3/5 - SIGWX Inferior (SUP-FL250)...")
        images["sigwx"] = self.get_redemet_sigwx("siginf")
        
        logging.info("")
        logging.info("4/5 - Ventos 850 hPa (~1500m)...")
        images["ventos_850"] = self.get_redemet_ventos_850()
        
        logging.info("")
        logging.info("5/5 - Radar Windy (screenshot SP)...")
        images["radar"] = self.get_windy_screenshot("radar")
        
        logging.info("")
        available = {k: v for k, v in images.items() if v}
        logging.info(f"Resultado: {len(available)}/{len(images)} imagens disponiveis")
        logging.info("=" * 50)
        
        return images


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Imagens Meteorologicas REVO - Alta Qualidade')
    parser.add_argument('--test', action='store_true', help='Baixa todas as imagens (teste)')
    parser.add_argument('--radar', action='store_true', help='Baixa radar (Windy)')
    parser.add_argument('--satelite', action='store_true', help='Baixa satelite (NOAA GEOCOLOR)')
    parser.add_argument('--ir', action='store_true', help='Baixa infravermelho (NOAA)')
    parser.add_argument('--windy', type=str, help='Screenshot Windy (radar/satellite/clouds/wind/rain)')
    parser.add_argument('--all', action='store_true', help='Baixa pacote completo')
    
    args = parser.parse_args()
    
    client = WeatherImagesClient()
    
    print("=" * 60)
    print("IMAGENS METEOROLOGICAS - REVO (Alta Qualidade)")
    print("Fontes: Windy (radar), NOAA GOES-16 (satelite)")
    print("=" * 60)
    
    if args.test or args.all:
        images = client.get_weather_update_package()
        print("")
        print("Resultados:")
        for name, path in images.items():
            if path:
                size = os.path.getsize(path) if os.path.exists(path) else 0
                print(f"  {name}: {path} ({size/1024:.0f} KB)")
            else:
                print(f"  {name}: FALHA")
        return
    
    if args.radar:
        img = client.get_radar_image()
        print(f"Radar: {img or 'Falha'}")
    
    if args.satelite:
        img = client.get_noaa_satellite("geocolor")
        print(f"Satelite: {img or 'Falha'}")
    
    if args.ir:
        img = client.get_noaa_satellite("ir_band13")
        print(f"Infravermelho: {img or 'Falha'}")
    
    if args.windy:
        img = client.get_windy_screenshot(args.windy)
        print(f"Windy {args.windy}: {img or 'Falha'}")
    
    if not any([args.test, args.radar, args.satelite, args.ir, args.windy, args.all]):
        print("")
        print("Fontes disponiveis:")
        print("  - Radar: Windy (screenshot via Selenium)")
        print("  - Satelite GEOCOLOR: NOAA GOES-16 (America do Sul)")
        print("  - Satelite IR: NOAA GOES-16 (infravermelho)")
        print("")
        print("Use --test para baixar todas as imagens")


if __name__ == "__main__":
    main()
