"""
Modulo de Calculo de Empty Legs, Hangar Flights e Custos Operacionais
REVO - Sistema de KPIs Automaticos
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import logging
import json
import os
import re

# URL AISWEB ROTAER - fonte oficial DECEA para coordenadas de aeródromos
AISWEB_ROTAER_URL = "https://aisweb.decea.mil.br/?i=aerodromos&p=rotaer"
AISWEB_AERODROMO_URL = "https://aisweb.decea.mil.br/?i=aerodromos&codigo={icao}"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class PTAXFetcher:
    """Obtem cotacao PTAX do Banco Central do Brasil"""
    
    BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"
    CACHE_FILE = "ptax_cache.json"
    CACHE_DURATION_HOURS = 24
    
    def __init__(self):
        self._cache = self._load_cache()
    
    def _load_cache(self):
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
    
    def _save_cache(self):
        try:
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(self._cache, f)
        except Exception as e:
            logging.warning(f"Erro ao salvar cache PTAX: {e}")
    
    def _is_cache_valid(self, cache_key):
        if cache_key not in self._cache:
            return False
        cached_time = datetime.fromisoformat(self._cache[cache_key].get('timestamp', '2000-01-01'))
        return (datetime.now() - cached_time).total_seconds() < self.CACHE_DURATION_HOURS * 3600
    
    def get_ptax_atual(self):
        """Obtem a cotacao PTAX mais recente disponivel (venda)"""
        cache_key = "ptax_atual"
        
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]['valor']
        
        try:
            url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados/ultimos/1?formato=json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                ptax = float(data[0]['valor'])
                self._cache[cache_key] = {
                    'valor': ptax,
                    'timestamp': datetime.now().isoformat()
                }
                self._save_cache()
                logging.info(f"PTAX atual obtido: R$ {ptax:.4f}")
                return ptax
            
        except Exception as e:
            logging.warning(f"Erro ao obter PTAX da API BCB: {e}")
        
        try:
            url = f"{self.BASE_URL}/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
            params = {
                "@dataInicial": "'01-01-2025'",
                "@dataFinalCotacao": "'12-31-2025'",
                "$orderby": "dataHoraCotacao desc",
                "$top": 1,
                "$format": "json"
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('value') and len(data['value']) > 0:
                ptax = data['value'][0]['cotacaoVenda']
                self._cache[cache_key] = {
                    'valor': ptax,
                    'timestamp': datetime.now().isoformat()
                }
                self._save_cache()
                logging.info(f"PTAX atual obtido: R$ {ptax:.4f}")
                return ptax
            
        except Exception as e:
            logging.warning(f"Erro ao obter PTAX da API OLINDA: {e}")
        
        ptax_fallback = 5.50
        logging.warning(f"Usando PTAX fallback: R$ {ptax_fallback}")
        return ptax_fallback
    
    def get_ptax_media_periodo(self, data_inicio, data_fim):
        """Obtem a media do PTAX em um periodo"""
        try:
            di = data_inicio.strftime('%m-%d-%Y')
            df = data_fim.strftime('%m-%d-%Y')
            
            url = f"{self.BASE_URL}/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
            params = {
                "@dataInicial": f"'{di}'",
                "@dataFinalCotacao": f"'{df}'",
                "$format": "json"
            }
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if data.get('value'):
                cotacoes = [c['cotacaoVenda'] for c in data['value']]
                media = sum(cotacoes) / len(cotacoes)
                logging.info(f"PTAX media ({data_inicio} a {data_fim}): R$ {media:.4f}")
                return media
        
        except Exception as e:
            logging.warning(f"Erro ao obter PTAX medio: {e}")
        
        return self.get_ptax_atual()


class RotaerDataProvider:
    """Provedor de dados de helipontos e calculo de distancias - carrega do ROTAER"""
    
    HELIPONTOS_BASE = {
        'SIAV': {'nome': 'Hangar REVO (Helipark)', 'lat': -23.5100, 'lon': -46.8400, 'cidade': 'Barueri'},
        'SBGR': {'nome': 'Aeroporto Guarulhos', 'lat': -23.4356, 'lon': -46.4731, 'cidade': 'Guarulhos'},
        'SBSP': {'nome': 'Congonhas', 'lat': -23.6261, 'lon': -46.6564, 'cidade': 'Sao Paulo'},
        'SBMT': {'nome': 'Campo de Marte', 'lat': -23.5091, 'lon': -46.6378, 'cidade': 'Sao Paulo'},
        'SBRJ': {'nome': 'Santos Dumont', 'lat': -22.9105, 'lon': -43.1631, 'cidade': 'Rio de Janeiro'},
        'SBGL': {'nome': 'Galeao', 'lat': -22.8090, 'lon': -43.2506, 'cidade': 'Rio de Janeiro'},
        'SIIR': {'nome': 'Brascan Century Plaza', 'lat': -23.5867, 'lon': -46.6803, 'cidade': 'Sao Paulo'},
        'SDMN': {'nome': 'Continental Tower Cidade Jardim', 'lat': -23.5922, 'lon': -46.6947, 'cidade': 'Sao Paulo'},
        'SDOF': {'nome': 'Ed. Paladio Vila Olimpia', 'lat': -23.5958, 'lon': -46.6856, 'cidade': 'Sao Paulo'},
        'SDXQ': {'nome': 'Faria Lima Int. Plaza', 'lat': -23.5747, 'lon': -46.6894, 'cidade': 'Sao Paulo'},
        'SDCY': {'nome': 'Corporate Tower', 'lat': -23.5969, 'lon': -46.6919, 'cidade': 'Sao Paulo'},
        'SDBR': {'nome': 'Berrini', 'lat': -23.6028, 'lon': -46.6964, 'cidade': 'Sao Paulo'},
        'SDWD': {'nome': 'WTorre JK', 'lat': -23.5933, 'lon': -46.6894, 'cidade': 'Sao Paulo'},
        'SNGL': {'nome': 'Fazenda Boa Vista', 'lat': -23.2667, 'lon': -47.4833, 'cidade': 'Porto Feliz'},
        'SDLA': {'nome': 'Cond. Laranjeiras', 'lat': -23.2167, 'lon': -44.7167, 'cidade': 'Paraty'},
        'SJCG': {'nome': 'Angra dos Reis', 'lat': -23.0067, 'lon': -44.3183, 'cidade': 'Angra dos Reis'},
        'SBJH': {'nome': 'Catarina Aeroporto', 'lat': -23.4281, 'lon': -47.1653, 'cidade': 'Sao Roque'},
        'SDIL': {'nome': 'Ilhabela', 'lat': -23.7783, 'lon': -45.3575, 'cidade': 'Ilhabela'},
        'SDJD': {'nome': 'Juquehy Baleia', 'lat': -23.760833, 'lon': -45.7125, 'cidade': 'Sao Sebastiao'},
        'SDMS': {'nome': 'Maresias', 'lat': -23.7833, 'lon': -45.5500, 'cidade': 'Sao Sebastiao'},
        'SDRV': {'nome': 'Riviera Sao Lourenco', 'lat': -23.8167, 'lon': -46.1167, 'cidade': 'Bertioga'},
        'SIHP': {'nome': 'Hospital Sirio-Libanes', 'lat': -23.5558, 'lon': -46.6622, 'cidade': 'Sao Paulo'},
    }
    
    ALIASES_NOMES = {
        'guarulhos': 'SBGR',
        'aeroporto internacional de são paulo': 'SBGR',
        'aeroporto internacional de sao paulo': 'SBGR',
        'congonhas': 'SBSP',
        'aeroporto de congonhas': 'SBSP',
        'campo de marte': 'SBMT',
        'santos dumont': 'SBRJ',
        'galeao': 'SBGL',
        'galeão': 'SBGL',
        'helipark': 'SIAV',
        'carapicuíba: helipark': 'SIAV',
        'carapicuiba: helipark': 'SIAV',
        'itower': 'SDXQ',
        'barueri: itower': 'SDXQ',
        'brascan century plaza': 'SIIR',
        'itaim bibi: brascan': 'SIIR',
        'itaim bibi': 'SIIR',
        'continental tower': 'SDMN',
        'cidade jardim': 'SDMN',
        'jd. panorama': 'SDMN',
        'jardim panorama': 'SDMN',
        'corporate tower': 'SDCY',
        'edifício paladio': 'SDOF',
        'edificio paladio': 'SDOF',
        'paladio': 'SDOF',
        'vl. olímpia': 'SDOF',
        'vila olimpia': 'SDOF',
        'faria lima': 'SDXQ',
        'faria lima international plaza': 'SDXQ',
        'vl. n. conceição': 'SDXQ',
        'wtorre': 'SDWD',
        'wtorre jk': 'SDWD',
        'berrini': 'SDBR',
        'fazenda boa vista': 'SNGL',
        'porto feliz: fazenda boa vista': 'SNGL',
        'porto feliz': 'SNGL',
        'laranjeiras': 'SDLA',
        'condomínio laranjeiras': 'SDLA',
        'condominio laranjeiras': 'SDLA',
        'paraty': 'SDLA',
        'paraty :': 'SDLA',
        'angra dos reis': 'SJCG',
        'porto frade': 'SJCG',
        'iate clube': 'SJCG',
        'iate clube de santos': 'SJCG',
        'catarina': 'SBJH',
        'são roque': 'SBJH',
        'sao roque': 'SBJH',
        'catarina aeroporto executivo': 'SBJH',
        'ilhabela': 'SDIL',
        'indaiaúba': 'SDIL',
        'indaiuba': 'SDIL',
        'juquehy baleia': 'SDJD',
        'juqueí baleia': 'SDJD',
        'juquehy': 'SDJD',
        'maresias': 'SDMS',
        'são sebastião': 'SDMS',
        'sao sebastiao': 'SDMS',
        'ciclade': 'SDMS',
        'riviera': 'SDRV',
        'bertioga': 'SDRV',
        'são lourenço': 'SDRV',
        'riviera de são lourenço': 'SDRV',
        'hospital sírio': 'SIHP',
        'sirio-libanes': 'SIHP',
        'sírio-libanês': 'SIHP',
        'sírio-libânes': 'SIHP',
        'prefeitura do rio': 'SBRJ',
        'avibras': 'SIAV',
        'avibrás': 'SIAV',
        'reis': 'SJCG',
    }
    
    HELIPONTOS_CIDADE_SP = ['SIIR', 'SDXQ', 'SDWD', 'SDOF', 'SDMN', 'SDCY', 'SDBR', 'SIJF', 'SNJ6', 'SDFW', 'SNSZ']
    
    VELOCIDADE_CRUZEIRO_KMH = 250
    
    AISWEB_CACHE_FILE = "aisweb_coords_cache.json"
    AISWEB_CACHE_DURATION_DAYS = 90

    def __init__(self, rotaer_file='rotaer.xlsx'):
        self._cache_distancias = {}
        self._known_failures = set()
        self.HELIPONTOS = self.HELIPONTOS_BASE.copy()
        self._load_rotaer(rotaer_file)
        self._load_aisweb_cache()
        self._build_nome_index()
    
    def _dms_to_decimal(self, dms_str):
        """Converte coordenada DMS (ex: 23 46 08S ou 045 38 02W) para decimal."""
        if not dms_str or not isinstance(dms_str, str):
            return None
        dms_str = dms_str.strip().upper()
        # Padrão: DD(D) MM SS(N/S/E/W) - ex: 23 46 08S, 045 38 02W
        m = re.match(r'(\d{2,3})\s+(\d{2})\s+(\d{2})\s*([NSWE])', dms_str)
        if not m:
            return None
        graus, mins, segs = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hem = m.group(4)
        decimal = graus + mins / 60.0 + segs / 3600.0
        if hem in ('S', 'W'):
            decimal = -decimal
        return round(decimal, 6)

    def _load_aisweb_cache(self):
        """Carrega cache de coordenadas buscadas no AISWEB (incluindo falhas)."""
        try:
            path = os.path.join(os.path.dirname(__file__) or '.', self.AISWEB_CACHE_FILE)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                cutoff = (datetime.now() - timedelta(days=self.AISWEB_CACHE_DURATION_DAYS)).isoformat()
                n_ok = 0
                n_fail = 0
                for icao, entry in list(data.items()):
                    if entry.get('timestamp', '') > cutoff:
                        if entry.get('failed', False) or entry.get('lat') is None:
                            self._known_failures.add(icao.upper())
                            n_fail += 1
                        else:
                            self.HELIPONTOS[icao.upper()] = {
                                'nome': entry.get('nome', icao),
                                'lat': entry['lat'],
                                'lon': entry['lon'],
                                'cidade': entry.get('cidade', ''),
                                '_aisweb': True
                            }
                            n_ok += 1
                if data:
                    logging.info(f"Cache AISWEB carregado: {n_ok} aeródromos + {n_fail} falhas conhecidas")
        except Exception as e:
            logging.debug(f"Cache AISWEB não carregado: {e}")

    def _save_aisweb_cache(self, icao, lat, lon, nome='', cidade=''):
        """Salva coordenada (ou falha) no cache AISWEB."""
        try:
            path = os.path.join(os.path.dirname(__file__) or '.', self.AISWEB_CACHE_FILE)
            data = {}
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data[icao.upper()] = {
                'lat': lat, 'lon': lon, 'nome': nome, 'cidade': cidade,
                'timestamp': datetime.now().isoformat(),
                'failed': lat is None
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if lat is None:
                self._known_failures.add(icao.upper())
        except Exception as e:
            logging.debug(f"Erro ao salvar cache AISWEB: {e}")

    def _fetch_coordenadas_aisweb(self, icao):
        """Busca coordenadas no AISWEB ROTAER (fonte oficial DECEA). Retorna (lat, lon) ou (None, None).
        Falhas sao cacheadas para evitar re-consultas HTTP lentas."""
        icao = str(icao).upper().strip() if icao else ''
        if len(icao) != 4 or not icao.isalnum():
            return None, None
        try:
            url = AISWEB_AERODROMO_URL.format(icao=icao)
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'REVO-Dashboard/1.0'})
            resp.raise_for_status()
            text = resp.text
            match = re.search(r'(\d{2,3}\s+\d{2}\s+\d{2}\s*[NS])\s*/\s*(\d{2,3}\s+\d{2}\s+\d{2}\s*[WE])', text)
            if not match:
                self._save_aisweb_cache(icao, None, None)
                return None, None
            lat_dms, lon_dms = match.group(1).strip(), match.group(2).strip()
            lat = self._dms_to_decimal(lat_dms)
            lon = self._dms_to_decimal(lon_dms)
            if lat is not None and lon is not None:
                logging.info(f"AISWEB: {icao} = {lat:.6f}, {lon:.6f} (fonte: ROTAER)")
                self.HELIPONTOS[icao] = {
                    'nome': icao, 'lat': lat, 'lon': lon, 'cidade': '', '_aisweb': True
                }
                self._save_aisweb_cache(icao, lat, lon)
                return lat, lon
            self._save_aisweb_cache(icao, None, None)
        except Exception as e:
            logging.debug(f"AISWEB fetch {icao}: {e}")
            self._save_aisweb_cache(icao, None, None)
        return None, None

    def _load_rotaer(self, rotaer_file):
        """Carrega helipontos do ROTAER. Prioridade: CSV completo > XLSX legado."""
        import pandas as pd
        loaded = 0

        # 1. CSV completo (5800+ aerodromos com lat/lon decimal)
        csv_candidates = [
            os.path.join('data', 'rotaer.csv'),
            os.path.join(os.path.dirname(__file__) or '.', '..', 'data', 'rotaer.csv'),
            'rotaer.csv',
        ]
        for csv_path in csv_candidates:
            try:
                if os.path.exists(csv_path):
                    df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
                    for _, row in df.iterrows():
                        icao = str(row.get('icao', '')).strip().upper()
                        if icao and len(icao) == 4 and icao not in self.HELIPONTOS:
                            lat = row.get('latitude')
                            lon = row.get('longitude')
                            if pd.notna(lat) and pd.notna(lon):
                                self.HELIPONTOS[icao] = {
                                    'nome': str(row.get('nome', icao)),
                                    'lat': float(lat),
                                    'lon': float(lon),
                                    'cidade': str(row.get('cidade', ''))
                                }
                                loaded += 1
                    if loaded > 0:
                        logging.info(f"ROTAER CSV carregado: {loaded} aeródromos de {csv_path}")
                        break
            except Exception as e:
                logging.debug(f"Erro ao carregar ROTAER CSV {csv_path}: {e}")

        # 2. XLSX legado (fallback)
        try:
            if os.path.exists(rotaer_file):
                df = pd.read_excel(rotaer_file)
                n_before = len(self.HELIPONTOS)
                for _, row in df.iterrows():
                    icao = str(row.get('Código ICAO', '')).strip().upper()
                    if icao and len(icao) == 4 and icao not in self.HELIPONTOS:
                        lat = row.get('Latitude (Decimal)')
                        lon = row.get('Longitude (Decimal)')
                        nome = str(row.get('Nome do Aeródromo', icao))
                        cidade = str(row.get('Localização', ''))
                        if pd.notna(lat) and pd.notna(lon):
                            self.HELIPONTOS[icao] = {
                                'nome': nome,
                                'lat': float(lat),
                                'lon': float(lon),
                                'cidade': cidade.replace('\n', ' ')
                            }
                n_xlsx = len(self.HELIPONTOS) - n_before
                if n_xlsx > 0:
                    logging.info(f"ROTAER XLSX adicional: +{n_xlsx} helipontos")
        except Exception as e:
            logging.debug(f"Erro ao carregar ROTAER XLSX: {e}")

        logging.info(f"Total helipontos: {len(self.HELIPONTOS)}")
    
    def _build_nome_index(self):
        """Constroi indice de nomes para busca"""
        self._nome_para_icao = {}
        for icao, info in self.HELIPONTOS.items():
            nome_lower = info['nome'].lower()
            self._nome_para_icao[nome_lower] = icao
            palavras = nome_lower.split()
            if len(palavras) > 1:
                self._nome_para_icao[palavras[0]] = icao
    
    def _resolver_nome_para_icao(self, nome):
        """Tenta resolver um nome descritivo para codigo ICAO"""
        if not nome:
            return None
        
        nome_clean = nome.strip().upper()
        if nome_clean in self.HELIPONTOS:
            return nome_clean
        
        nome_lower = nome.lower().strip()
        
        for alias, icao in self.ALIASES_NOMES.items():
            if alias in nome_lower:
                return icao
        
        if nome_lower in self._nome_para_icao:
            return self._nome_para_icao[nome_lower]
        
        return None
    
    def get_coordenadas(self, icao_code):
        """Retorna coordenadas de um heliponto do ROTAER CSV (5800+ aerodromos)."""
        icao = self._resolver_nome_para_icao(icao_code)
        if not icao:
            icao = str(icao_code).upper().strip() if icao_code and len(str(icao_code)) == 4 else None
        if icao and icao in self.HELIPONTOS:
            h = self.HELIPONTOS[icao]
            return h['lat'], h['lon']
        return None, None
    
    def get_icao_from_nome(self, nome):
        """Retorna codigo ICAO a partir de um nome"""
        return self._resolver_nome_para_icao(nome)
    
    def _haversine(self, lat1, lon1, lat2, lon2):
        """Calcula distancia em km usando formula de Haversine"""
        R = 6371
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        return R * c
    
    def calcular_distancia(self, origem, destino):
        """Calcula distancia em km entre dois helipontos"""
        cache_key = f"{origem}_{destino}"
        if cache_key in self._cache_distancias:
            return self._cache_distancias[cache_key]
        
        lat1, lon1 = self.get_coordenadas(origem)
        lat2, lon2 = self.get_coordenadas(destino)
        
        if lat1 is None or lat2 is None:
            logging.debug(f"ICAO nao encontrado no ROTAER: {origem} ou {destino} → fallback 50km")
            return 50.0
        
        distancia = self._haversine(lat1, lon1, lat2, lon2)
        self._cache_distancias[cache_key] = distancia
        return distancia
    
    def get_velocidade_aeronave(self, prefixo):
        """Retorna velocidade de cruzeiro em km/h por aeronave"""
        prefixo_upper = str(prefixo).upper().strip() if prefixo else ''
        if 'OMB' in prefixo_upper or 'OMH' in prefixo_upper:
            return 259.28
        elif 'OOE' in prefixo_upper:
            return 222.24
        return 259.28
    
    def calcular_tempo_voo(self, origem, destino, prefixo=None):
        """Calcula tempo de voo em horas entre dois helipontos"""
        velocidade_kmh = self.get_velocidade_aeronave(prefixo)
        
        distancia = self.calcular_distancia(origem, destino)
        tempo_cruzeiro = distancia / velocidade_kmh
        tempo_total = tempo_cruzeiro + (5/60)
        
        return round(tempo_total, 3)
    
    def is_heliponto_cidade_sp(self, icao_code):
        """Verifica se o heliponto esta na cidade de SP"""
        return icao_code.upper().strip() in self.HELIPONTOS_CIDADE_SP
    
    def get_nome_heliponto(self, icao_code):
        """Retorna nome do heliponto"""
        icao = self._resolver_nome_para_icao(icao_code)
        if icao and icao in self.HELIPONTOS:
            return self.HELIPONTOS[icao]['nome']
        return icao_code


class CostCalculator:
    """Calculadora de custos operacionais da frota.
    Usada APENAS para estimar custos de meses onde não há dados reais (OTA).
    Quando há custos oficiais no Excel, estes têm prioridade."""
    
    AERONAVES = {
        'PR-OMH': {
            'modelo': 'EC155',
            'custo_fixo_brl': 465581.91,
            'custo_fixo_usd': 49789.08
        },
        'PR-OMB': {
            'modelo': 'EC155',
            'custo_fixo_brl': 465581.91,
            'custo_fixo_usd': 49789.08
        },
        'PR-OOE': {
            'modelo': 'EC135',
            'custo_fixo_brl': 394816.16,
            'custo_fixo_usd': 63213.79
        }
    }
    
    CUSTO_VARIAVEL_BRL = 832.00
    CUSTO_VARIAVEL_USD = 1194.34
    
    def __init__(self, ptax_fetcher=None):
        self.ptax_fetcher = ptax_fetcher or PTAXFetcher()
        self._ptax_cache = None
    
    def get_ptax(self):
        """Obtem PTAX com cache"""
        if self._ptax_cache is None:
            self._ptax_cache = self.ptax_fetcher.get_ptax_atual()
        return self._ptax_cache
    
    def calcular_custo_fixo_mensal(self, prefixo, ptax=None):
        """Calcula custo fixo mensal de uma aeronave"""
        if ptax is None:
            ptax = self.get_ptax()
        
        if prefixo not in self.AERONAVES:
            logging.warning(f"Aeronave nao encontrada: {prefixo}")
            return 0
        
        aeronave = self.AERONAVES[prefixo]
        custo = aeronave['custo_fixo_brl'] + (aeronave['custo_fixo_usd'] * ptax)
        return custo
    
    def calcular_custo_fixo_frota_mensal(self, ptax=None):
        """Calcula custo fixo mensal total da frota"""
        if ptax is None:
            ptax = self.get_ptax()
        
        total = 0
        for prefixo in self.AERONAVES:
            total += self.calcular_custo_fixo_mensal(prefixo, ptax)
        return total
    
    def calcular_custo_variavel_hora(self, ptax=None):
        """Calcula custo variavel por hora voada"""
        if ptax is None:
            ptax = self.get_ptax()
        
        return self.CUSTO_VARIAVEL_BRL + (self.CUSTO_VARIAVEL_USD * ptax)
    
    def calcular_custo_voo(self, tempo_horas, ptax=None):
        """Calcula custo variavel de um voo"""
        custo_hora = self.calcular_custo_variavel_hora(ptax)
        return custo_hora * tempo_horas
    
    def calcular_custo_total(self, horas_totais, ptax=None):
        """Calcula custo total (fixo + variavel)"""
        if ptax is None:
            ptax = self.get_ptax()
        
        custo_fixo = self.calcular_custo_fixo_frota_mensal(ptax)
        custo_variavel = self.calcular_custo_voo(horas_totais, ptax)
        custo_total = custo_fixo + custo_variavel
        
        return {
            'custo_fixo': custo_fixo,
            'custo_variavel': custo_variavel,
            'custo_total': custo_total,
            'ptax': ptax
        }
    
    def calcular_custo_medio(self, horas_totais, ptax=None):
        """Calcula custo medio por hora (CMe = CT/h)"""
        if horas_totais <= 0:
            return 0
        
        custos = self.calcular_custo_total(horas_totais, ptax)
        return custos['custo_total'] / horas_totais
    
    def calcular_custo_marginal(self, ptax=None):
        """Calcula custo marginal (CMg = custo variavel/hora)"""
        return self.calcular_custo_variavel_hora(ptax)
    
    def get_resumo_custos(self, ptax=None):
        """Retorna resumo completo de custos"""
        if ptax is None:
            ptax = self.get_ptax()
        
        custos_aeronaves = {}
        for prefixo, info in self.AERONAVES.items():
            custo_fixo = self.calcular_custo_fixo_mensal(prefixo, ptax)
            custos_aeronaves[prefixo] = {
                'modelo': info['modelo'],
                'formula_brl': info['custo_fixo_brl'],
                'formula_usd': info['custo_fixo_usd'],
                'custo_mensal': custo_fixo
            }
        
        custo_fixo_frota = self.calcular_custo_fixo_frota_mensal(ptax)
        custo_var_hora = self.calcular_custo_variavel_hora(ptax)
        
        return {
            'ptax': ptax,
            'aeronaves': custos_aeronaves,
            'custo_fixo_frota_mensal': custo_fixo_frota,
            'custo_fixo_frota_anual': custo_fixo_frota * 12,
            'custo_variavel_hora': custo_var_hora,
            'formula_variavel_brl': self.CUSTO_VARIAVEL_BRL,
            'formula_variavel_usd': self.CUSTO_VARIAVEL_USD
        }


class EmptyLegCalculator:
    """Calculadora de Empty Legs e Hangar Flights"""
    
    HANGAR_BASE = 'SIAV'
    THRESHOLD_HORAS = 3.0
    
    def __init__(self, csv_path='dados_reservas.csv'):
        self.csv_path = csv_path
        self.rotaer = RotaerDataProvider()
        self.cost_calc = CostCalculator()
        self.df_voos = None
        self.df_empty_legs = None
    
    def carregar_voos_salesforce(self, csv_path=None):
        """Carrega voos do Salesforce (removendo duplicatas por Voo_Id)"""
        if csv_path:
            self.csv_path = csv_path
        
        try:
            df = pd.read_csv(self.csv_path, encoding='utf-8-sig')
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            
            total_registros = len(df)
            
            if 'Voo_Id' in df.columns:
                df = df.drop_duplicates(subset=['Voo_Id'], keep='first')
                logging.info(f"Registros: {total_registros} -> {len(df)} voos unicos (removidas {total_registros - len(df)} duplicatas)")
            
            self.df_voos = df
            logging.info(f"Carregados {len(self.df_voos)} voos do Salesforce")
            return True
        except Exception as e:
            logging.error(f"Erro ao carregar voos: {e}")
            return False
    
    def _extrair_origem_destino(self, row):
        """Extrai origem e destino de uma rota (prefere ICAO)"""
        rota_icao = row.get('Voo_Rota_ICAO') if isinstance(row, dict) else row.get('Voo_Rota_ICAO', None) if hasattr(row, 'get') else None
        rota = rota_icao if pd.notna(rota_icao) else (row.get('Voo_Rota') if isinstance(row, dict) else row.get('Voo_Rota', None) if hasattr(row, 'get') else row)
        
        if pd.isna(rota):
            return None, None
        
        rota_str = str(rota)
        
        if '>' in rota_str:
            partes = rota_str.split('>')
            origem = partes[0].strip()
            destino = partes[-1].strip()
            return origem, destino
        
        return None, None
    
    def _categorizar_voo(self, tipo):
        """Categoriza voo como Charter ou Shuttle"""
        tipo_lower = str(tipo).lower()
        if 'charter' in tipo_lower:
            return 'Charter'
        elif 'shuttle' in tipo_lower or 'full cabin' in tipo_lower:
            return 'Shuttle'
        return 'Outros'
    
    def _gerar_empty_leg(self, tipo, origem, destino, aeronave, data_hora, voo_ref_id):
        """Gera um registro de empty leg"""
        tempo_voo = self.rotaer.calcular_tempo_voo(origem, destino, aeronave)
        distancia = self.rotaer.calcular_distancia(origem, destino)
        custo = self.cost_calc.calcular_custo_voo(tempo_voo)
        
        return {
            'Tipo_Empty': tipo,
            'Origem': origem,
            'Destino': destino,
            'Origem_Nome': self.rotaer.get_nome_heliponto(origem),
            'Destino_Nome': self.rotaer.get_nome_heliponto(destino),
            'Aeronave': aeronave,
            'Data_Hora': data_hora,
            'Tempo_Voo_Horas': tempo_voo,
            'Distancia_KM': distancia,
            'Custo_BRL': custo,
            'Voo_Referencia_ID': voo_ref_id
        }
    
    def _processar_voos_shuttle(self, df_aeronave):
        """Processa voos shuttle e gera empty legs"""
        empty_legs = []
        
        df_sorted = df_aeronave.sort_values('Voo_DataHora').reset_index(drop=True)
        
        for i, row in df_sorted.iterrows():
            origem, destino = self._extrair_origem_destino(row)
            if not origem or not destino:
                continue
            
            data_hora = row['Voo_DataHora']
            aeronave = row.get('Voo_Prefixo', 'UNKNOWN')
            voo_id = row.get('Voo_ID', f'VOO_{i}')
            
            is_cidade_origem = self.rotaer.is_heliponto_cidade_sp(origem)
            is_sbgr_origem = origem.upper() == 'SBGR'
            is_cidade_destino = self.rotaer.is_heliponto_cidade_sp(destino)
            is_sbgr_destino = destino.upper() == 'SBGR'
            
            if is_cidade_origem and is_sbgr_destino:
                tempo_posicionamento = self.rotaer.calcular_tempo_voo(self.HANGAR_BASE, origem)
                hora_posicionamento = data_hora - timedelta(hours=tempo_posicionamento + 0.25)
                
                empty_legs.append(self._gerar_empty_leg(
                    'POSICIONAMENTO_IDA',
                    self.HANGAR_BASE,
                    origem,
                    aeronave,
                    hora_posicionamento,
                    voo_id
                ))
            
            if is_sbgr_destino:
                hora_chegada_sbgr = data_hora + timedelta(hours=self.rotaer.calcular_tempo_voo(origem, destino))
                
                proximo_voo = None
                for j in range(i + 1, len(df_sorted)):
                    prox_row = df_sorted.iloc[j]
                    prox_origem, _ = self._extrair_origem_destino(prox_row)
                    if prox_origem and prox_origem.upper() == 'SBGR':
                        diff_horas = (prox_row['Voo_DataHora'] - hora_chegada_sbgr).total_seconds() / 3600
                        if diff_horas <= self.THRESHOLD_HORAS:
                            proximo_voo = prox_row
                        break
                
                if proximo_voo is None:
                    hora_retorno = hora_chegada_sbgr + timedelta(minutes=15)
                    empty_legs.append(self._gerar_empty_leg(
                        'RETORNO_HANGAR',
                        'SBGR',
                        self.HANGAR_BASE,
                        aeronave,
                        hora_retorno,
                        voo_id
                    ))
            
            if is_sbgr_origem and is_cidade_destino:
                hora_chegada_cidade = data_hora + timedelta(hours=self.rotaer.calcular_tempo_voo(origem, destino))
                
                proximo_voo_sbgr = None
                for j in range(i + 1, len(df_sorted)):
                    prox_row = df_sorted.iloc[j]
                    prox_origem, prox_destino = self._extrair_origem_destino(prox_row)
                    if prox_origem and self.rotaer.is_heliponto_cidade_sp(prox_origem) and prox_destino == 'SBGR':
                        diff_horas = (prox_row['Voo_DataHora'] - hora_chegada_cidade).total_seconds() / 3600
                        if diff_horas <= self.THRESHOLD_HORAS:
                            proximo_voo_sbgr = prox_row
                        break
                
                if proximo_voo_sbgr is None:
                    hora_retorno = hora_chegada_cidade + timedelta(minutes=15)
                    empty_legs.append(self._gerar_empty_leg(
                        'RETORNO_HANGAR',
                        destino,
                        self.HANGAR_BASE,
                        aeronave,
                        hora_retorno,
                        voo_id
                    ))
        
        return empty_legs
    
    def _processar_voos_charter(self, df_aeronave):
        """Processa voos charter e gera empty legs (retorno ao hangar)"""
        empty_legs = []
        
        helipontos_proximos_hangar = [
            'SIAV', 'SBSP', 'SBMT', 'SIIR', 'SDXQ', 'SDWD', 'SDOF', 'SDMN', 
            'SDCY', 'SDBR', 'SIJF', 'SNJ6', 'SDFW', 'SNSZ', 'SBJH'
        ]
        
        for _, row in df_aeronave.iterrows():
            origem, destino = self._extrair_origem_destino(row)
            if not origem or not destino:
                continue
            
            destino_upper = destino.upper() if destino else ''
            
            if destino_upper in helipontos_proximos_hangar:
                continue
            
            if destino_upper == self.HANGAR_BASE:
                continue
            
            distancia_destino_hangar = self.rotaer.calcular_distancia(destino, self.HANGAR_BASE)
            if distancia_destino_hangar < 60:
                continue
            
            data_hora = row['Voo_DataHora']
            aeronave = row.get('Voo_Prefixo', 'UNKNOWN')
            voo_id = row.get('Voo_Id', 'UNKNOWN')
            
            tempo_voo_ida = self.rotaer.calcular_tempo_voo(origem, destino, aeronave)
            hora_chegada = data_hora + timedelta(hours=tempo_voo_ida)
            hora_retorno = hora_chegada + timedelta(minutes=30)
            
            empty_legs.append(self._gerar_empty_leg(
                'CHARTER_RETORNO',
                destino,
                self.HANGAR_BASE,
                aeronave,
                hora_retorno,
                voo_id
            ))
        
        return empty_legs
    
    def calcular_todos_empty_legs(self):
        """Calcula todos os empty legs da operacao"""
        if self.df_voos is None:
            if not self.carregar_voos_salesforce():
                return pd.DataFrame()
        
        if 'Voo_Tipo' not in self.df_voos.columns:
            logging.warning("Coluna Voo_Tipo nao encontrada")
            return pd.DataFrame()
        
        self.df_voos['Categoria'] = self.df_voos['Voo_Tipo'].apply(self._categorizar_voo)
        
        all_empty_legs = []
        
        if 'Voo_Prefixo' in self.df_voos.columns:
            for prefixo in self.df_voos['Voo_Prefixo'].dropna().unique():
                df_aeronave = self.df_voos[self.df_voos['Voo_Prefixo'] == prefixo].copy()
                
                df_shuttle = df_aeronave[df_aeronave['Categoria'] == 'Shuttle']
                if not df_shuttle.empty:
                    all_empty_legs.extend(self._processar_voos_shuttle(df_shuttle))
                
                df_charter = df_aeronave[df_aeronave['Categoria'] == 'Charter']
                if not df_charter.empty:
                    all_empty_legs.extend(self._processar_voos_charter(df_charter))
        else:
            df_shuttle = self.df_voos[self.df_voos['Categoria'] == 'Shuttle']
            if not df_shuttle.empty:
                all_empty_legs.extend(self._processar_voos_shuttle(df_shuttle))
            
            df_charter = self.df_voos[self.df_voos['Categoria'] == 'Charter']
            if not df_charter.empty:
                all_empty_legs.extend(self._processar_voos_charter(df_charter))
        
        self.df_empty_legs = pd.DataFrame(all_empty_legs)
        
        if not self.df_empty_legs.empty:
            self.df_empty_legs = self.df_empty_legs.sort_values('Data_Hora').reset_index(drop=True)
            logging.info(f"Gerados {len(self.df_empty_legs)} empty legs")
        
        return self.df_empty_legs
    
    def exportar_empty_legs(self, output_path='dados_empty_legs.csv'):
        """Exporta empty legs para CSV"""
        if self.df_empty_legs is None or self.df_empty_legs.empty:
            logging.warning("Nenhum empty leg para exportar")
            return False
        
        try:
            self.df_empty_legs.to_csv(output_path, index=False, encoding='utf-8-sig')
            logging.info(f"Empty legs exportados: {output_path}")
            return True
        except Exception as e:
            logging.error(f"Erro ao exportar empty legs: {e}")
            return False
    
    def get_resumo_empty_legs(self):
        """Retorna resumo dos empty legs calculados"""
        if self.df_empty_legs is None or self.df_empty_legs.empty:
            return None
        
        return {
            'total_empty_legs': len(self.df_empty_legs),
            'tempo_total_horas': self.df_empty_legs['Tempo_Voo_Horas'].sum(),
            'distancia_total_km': self.df_empty_legs['Distancia_KM'].sum(),
            'custo_total_brl': self.df_empty_legs['Custo_BRL'].sum(),
            'por_tipo': self.df_empty_legs.groupby('Tipo_Empty').agg({
                'Tempo_Voo_Horas': 'sum',
                'Custo_BRL': 'sum',
                'Tipo_Empty': 'count'
            }).rename(columns={'Tipo_Empty': 'quantidade'}).to_dict('index'),
            'por_aeronave': self.df_empty_legs.groupby('Aeronave').agg({
                'Tempo_Voo_Horas': 'sum',
                'Custo_BRL': 'sum',
                'Aeronave': 'count'
            }).rename(columns={'Aeronave': 'quantidade'}).to_dict('index')
        }
    
    def calcular_custos_operacao_completa(self):
        """Calcula custos completos incluindo voos SF + empty legs"""
        if self.df_empty_legs is None:
            self.calcular_todos_empty_legs()
        
        horas_empty = self.df_empty_legs['Tempo_Voo_Horas'].sum() if not self.df_empty_legs.empty else 0
        custo_empty = self.df_empty_legs['Custo_BRL'].sum() if not self.df_empty_legs.empty else 0
        
        horas_sf = 0
        custo_sf = 0
        
        resumo_custos = self.cost_calc.get_resumo_custos()
        
        return {
            'horas_empty_legs': horas_empty,
            'custo_empty_legs': custo_empty,
            'horas_voos_sf': horas_sf,
            'custo_voos_sf': custo_sf,
            'horas_totais': horas_empty + horas_sf,
            'custo_variavel_total': custo_empty + custo_sf,
            'custo_fixo_mensal': resumo_custos['custo_fixo_frota_mensal'],
            'custo_total_mensal': resumo_custos['custo_fixo_frota_mensal'] + custo_empty + custo_sf,
            'resumo_custos': resumo_custos
        }


def main():
    """Funcao principal para execucao standalone"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Calculadora de Empty Legs e Custos - REVO')
    parser.add_argument('--csv', type=str, default='dados_reservas.csv', help='CSV de voos do Salesforce')
    parser.add_argument('--output', type=str, default='dados_empty_legs.csv', help='CSV de saida')
    parser.add_argument('--custos', action='store_true', help='Exibir resumo de custos')
    
    args = parser.parse_args()
    
    calculator = EmptyLegCalculator(args.csv)
    
    df_empty = calculator.calcular_todos_empty_legs()
    
    if not df_empty.empty:
        calculator.exportar_empty_legs(args.output)
        
        resumo = calculator.get_resumo_empty_legs()
        print("\n" + "="*60)
        print("RESUMO DE EMPTY LEGS")
        print("="*60)
        print(f"Total de Empty Legs: {resumo['total_empty_legs']}")
        print(f"Tempo Total Voado: {resumo['tempo_total_horas']:.2f} horas")
        print(f"Distancia Total: {resumo['distancia_total_km']:.1f} km")
        print(f"Custo Total: R$ {resumo['custo_total_brl']:,.2f}")
    
    if args.custos:
        custos = calculator.calcular_custos_operacao_completa()
        print("\n" + "="*60)
        print("RESUMO DE CUSTOS OPERACIONAIS")
        print("="*60)
        print(f"PTAX: R$ {custos['resumo_custos']['ptax']:.4f}")
        print(f"Custo Fixo Mensal Frota: R$ {custos['custo_fixo_mensal']:,.2f}")
        print(f"Custo Variavel (Empty Legs): R$ {custos['custo_empty_legs']:,.2f}")
        print(f"Custo Total Mensal: R$ {custos['custo_total_mensal']:,.2f}")


if __name__ == "__main__":
    main()
