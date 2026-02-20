"""
Monitor da Tendencia do Tempo - IPMet Radar
Faz scraping de https://www.ipmetradar.com.br/2tempo.php
Extrai texto + imagens da secao "TENDENCIA DO TEMPO PARA O ESTADO DE SAO PAULO"
Envia via Telegram quando houver mudanca.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

IPMET_URL = 'https://www.ipmetradar.com.br/2tempo.php'
IPMET_BASE_URL = 'https://www.ipmetradar.com.br'

STATE_FILE = Path(os.environ.get(
    'IPMET_TENDENCIA_STATE_FILE',
    Path(__file__).parent / '.ipmet_tendencia_state.json'
))


def _fetch_page():
    """Baixa HTML da pagina do boletim do tempo."""
    req = urllib.request.Request(IPMET_URL, headers={
        'User-Agent': 'REVO-FlightMonitor/1.0',
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        # Tentar UTF-8 primeiro (pagina atual usa UTF-8)
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('latin-1', errors='replace')


def _extrair_tendencia(html):
    """Extrai secao TENDENCIA DO TEMPO: texto de cada dia e URLs das imagens.

    Retorna dict:
        {
            'atualizacao': '20/02/2026 as 11:45h',
            'dias': [
                {'titulo': 'Sexta-feira (20/02)', 'texto': '...', 'imagem': '/imagens/boletim/...PNG'},
                ...
            ]
        }
    """
    # Localizar inicio da secao TENDENCIA
    marker = re.search(
        r'TEND[ÊE]NCIA\s+DO\s+TEMPO\s+PARA\s+O\s+ESTADO\s+DE\s+S[ÃA]O\s+PAULO',
        html, re.IGNORECASE,
    )
    if not marker:
        logger.warning('Secao TENDENCIA DO TEMPO nao encontrada na pagina')
        return None

    secao = html[marker.start():]
    # Limitar ao proximo grande bloco (fim da tabela)
    fim = secao.find('<!--Fim da altera')
    if fim == -1:
        fim = secao.find('Meteorologista respons')
    if fim > 0:
        secao = secao[:fim]

    # Extrair data de atualizacao
    atualiz_match = re.search(
        r'\([ÚU]ltima\s+atualiza[çc][ãa]o:\s*(.+?)\)',
        secao, re.IGNORECASE,
    )
    atualizacao = atualiz_match.group(1).strip() if atualiz_match else ''
    atualizacao = atualizacao.replace('&agrave;', 'à')

    # Extrair cada dia (blocos <!--Dia N -->)
    dias = []
    # Encontrar cada <td> com conteudo de dia
    blocos = re.split(r'<!--\s*Dia\s+\d+\s*-->', secao)
    for bloco in blocos[1:]:  # pular texto antes do primeiro dia
        # Titulo do dia (ex: "Sexta-feira (20/02)")
        titulo_match = re.search(r'<b>\s*(.+?)\s*</b>', bloco, re.DOTALL)
        titulo = titulo_match.group(1).strip() if titulo_match else ''
        titulo = re.sub(r'\s+', ' ', titulo)

        # Imagem
        img_match = re.search(r"src=['\"]([^'\"]*boletim[^'\"]*)['\"]", bloco, re.IGNORECASE)
        imagem = img_match.group(1) if img_match else ''

        # Texto da previsao (dentro de noticiaTEXTO)
        texto_match = re.search(r"class=['\"]noticiaTEXTO['\"][^>]*>(.*?)</div>", bloco, re.DOTALL | re.IGNORECASE)
        texto = ''
        if texto_match:
            texto = texto_match.group(1)
            texto = re.sub(r'<[^>]+>', ' ', texto)  # remover tags
            texto = re.sub(r'&[a-z]+;', ' ', texto)  # remover entidades
            texto = re.sub(r'\s+', ' ', texto).strip()

        if titulo or texto:
            dias.append({
                'titulo': titulo,
                'texto': texto,
                'imagem': imagem,
            })

    if not dias:
        logger.warning('Nenhum bloco de dia encontrado na secao TENDENCIA')
        return None

    return {
        'atualizacao': atualizacao,
        'dias': dias,
    }


def _content_hash(tendencia):
    """Gera hash do conteudo para detectar mudancas."""
    raw = json.dumps(tendencia, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_state():
    """Carrega estado anterior (hash do conteudo)."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            return data.get('hash', '')
        except Exception:
            pass
    return ''


def _save_state(content_hash):
    """Salva estado atual."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({'hash': content_hash}, indent=2),
        encoding='utf-8',
    )


def _download_image(url):
    """Baixa imagem e retorna caminho do arquivo temporario."""
    if not url:
        return None
    if url.startswith('/'):
        url = IPMET_BASE_URL + url
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'REVO-FlightMonitor/1.0',
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            ext = '.png' if url.lower().endswith('.png') else '.jpg'
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix='ipmet_')
            tmp.write(data)
            tmp.close()
            return tmp.name
    except Exception as e:
        logger.warning(f'Erro ao baixar imagem {url}: {e}')
        return None


def _format_header(tendencia):
    """Formata cabecalho para mensagem separada."""
    lines = ['<b>🌤 TENDÊNCIA DO TEMPO - SÃO PAULO</b>']
    lines.append(f'<i>Fonte: IPMet/UNESP</i>')
    if tendencia['atualizacao']:
        lines.append(f'📅 Atualização: {tendencia["atualizacao"]}')
    return '\n'.join(lines)


def _format_caption(dia):
    """Formata legenda da imagem com titulo e texto do dia."""
    return f"{dia['titulo']}\n\n{dia['texto']}"


def _send_tendencia(notifier, tendencia):
    """Envia cabecalho + imagens com legendas via Telegram."""
    # Mensagem separada com cabecalho
    notifier.send_message(_format_header(tendencia))

    # Cada imagem com o texto do dia como legenda
    for dia in tendencia['dias']:
        if dia['imagem']:
            img_path = _download_image(dia['imagem'])
            if img_path:
                notifier.send_photo(img_path, _format_caption(dia))
                try:
                    os.unlink(img_path)
                except Exception:
                    pass


def check_and_notify(notifier):
    """Verifica se houve mudanca e envia via Telegram.

    Args:
        notifier: instancia de TelegramNotifier com metodos
                  send_message() e send_photo()

    Returns:
        dict com status da verificacao
    """
    try:
        html = _fetch_page()
    except Exception as e:
        logger.error(f'Erro ao buscar pagina IPMet: {e}')
        return {'status': 'error', 'detail': str(e)}

    tendencia = _extrair_tendencia(html)
    if not tendencia:
        return {'status': 'parse_error', 'detail': 'Secao TENDENCIA nao encontrada'}

    new_hash = _content_hash(tendencia)
    old_hash = _load_state()

    if new_hash == old_hash:
        logger.info('IPMet Tendencia: sem mudanca detectada')
        return {'status': 'unchanged'}

    logger.info('IPMet Tendencia: mudanca detectada, enviando...')

    _send_tendencia(notifier, tendencia)

    _save_state(new_hash)
    logger.info('IPMet Tendencia enviada com sucesso')
    return {'status': 'sent', 'atualizacao': tendencia.get('atualizacao', '')}


def force_send(notifier):
    """Forca envio independente de mudanca (util para teste)."""
    try:
        html = _fetch_page()
    except Exception as e:
        logger.error(f'Erro ao buscar pagina IPMet: {e}')
        return False

    tendencia = _extrair_tendencia(html)
    if not tendencia:
        logger.error('Secao TENDENCIA nao encontrada')
        return False

    _send_tendencia(notifier, tendencia)

    _save_state(_content_hash(tendencia))
    return True
