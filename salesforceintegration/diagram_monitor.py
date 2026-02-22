"""
Módulo de Monitoramento de Diagramas de Voos
Envia diagramas às 06h (hoje) e 18h (amanhã)
Detecta mudanças ao longo do dia e envia alertas
"""

import os
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

STATE_FILE = 'diagram_state.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_diagram_state():
    """Carrega estado anterior dos voos para comparação"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Erro ao carregar estado: {e}")
    return {'voos_hoje': [], 'voos_amanha': [], 'last_update': None}

def save_diagram_state(state):
    """Salva estado atual"""
    try:
        state['last_update'] = datetime.now().isoformat()
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Erro ao salvar estado: {e}")

def voos_to_signature(voos):
    """
    Converte lista de voos em uma assinatura única para comparação
    Retorna set de tuplas (data, hora, rota, prefixo)
    """
    signatures = set()
    for voo in voos:
        try:
            data_hora = voo.get('DataHoraVoo__c') or voo.get('Voo_DataHora', '')
            if data_hora:
                dt = datetime.fromisoformat(str(data_hora).replace('Z', '+00:00').replace('+00:00', ''))
                data = dt.strftime('%Y-%m-%d')
                hora = dt.strftime('%H:%M')
            else:
                data = ''
                hora = ''
            
            rota = voo.get('RotaAbreviada__c') or voo.get('Voo_Rota', '')
            prefixo = voo.get('Helicoptero__r', {})
            if isinstance(prefixo, dict):
                prefixo = prefixo.get('Prefixo__c', '')
            else:
                prefixo = voo.get('Voo_Prefixo', '')
            
            sig = (data, hora, str(rota), str(prefixo))
            signatures.add(sig)
        except Exception as e:
            logging.warning(f"Erro ao criar assinatura do voo: {e}")
            continue
    
    return signatures

def detect_changes(voos_novos, voos_antigos):
    """
    Detecta mudanças entre duas listas de voos
    Retorna (houve_mudanca, voos_adicionados, voos_removidos)
    """
    sig_novos = voos_to_signature(voos_novos)
    sig_antigos = voos_to_signature(voos_antigos)
    
    adicionados = sig_novos - sig_antigos
    removidos = sig_antigos - sig_novos
    
    houve_mudanca = len(adicionados) > 0 or len(removidos) > 0
    
    return houve_mudanca, adicionados, removidos

def send_diagram_scheduled(mode='morning'):
    """
    Envia diagrama programado
    mode='morning' (06h): voos de hoje
    mode='evening' (18h): voos de amanhã
    """
    from telegram_notifier import get_voos_salesforce, TelegramNotifier

    notifier = TelegramNotifier()
    voos_hoje, voos_amanha, _voos_depois, _voos_proximos = get_voos_salesforce()

    state = load_diagram_state()

    if mode == 'morning':
        titulo_dia = 'HOJE'
        voos = voos_hoje
        chart_file = 'chart_helicopteros_hoje.png'
        state_key = 'voos_hoje'
        data_str = datetime.now().strftime('%d/%m/%Y')
    else:
        titulo_dia = 'AMANHÃ'
        voos = voos_amanha
        chart_file = 'chart_helicopteros_amanha.png'
        state_key = 'voos_amanha'
        data_str = (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')
    
    if voos:
        chart_path = notifier._generate_single_day_diagram(
            voos,
            f'ROTAS {titulo_dia} - {data_str}',
            chart_file
        )
        
        caption = f"🚁 <b>ROTAS {titulo_dia} - {data_str}</b>"
        notifier.send_photo(chart_path, caption)
        logging.info(f"Diagrama {mode} enviado: {len(voos)} voos")
    else:
        notifier.send_message(f"📋 <b>ROTAS {titulo_dia} - {data_str}</b>\n\nNenhum voo programado.")
        logging.info(f"Nenhum voo para {mode}")
    
    state[state_key] = voos
    save_diagram_state(state)
    
    return True

def check_and_send_changes():
    """
    Verifica se houve mudanças nos voos e envia diagrama atualizado com alerta
    """
    from telegram_notifier import get_voos_salesforce, TelegramNotifier

    notifier = TelegramNotifier()
    voos_hoje, voos_amanha, _voos_depois, _voos_proximos = get_voos_salesforce()

    state = load_diagram_state()

    mudou_hoje, add_hoje, rem_hoje = detect_changes(voos_hoje, state.get('voos_hoje', []))
    mudou_amanha, add_amanha, rem_amanha = detect_changes(voos_amanha, state.get('voos_amanha', []))
    
    if mudou_hoje:
        logging.info(f"Mudança detectada HOJE: +{len(add_hoje)} -{len(rem_hoje)}")
        
        data_str = datetime.now().strftime('%d/%m/%Y')
        
        if voos_hoje:
            chart_path = notifier._generate_single_day_diagram(
                voos_hoje,
                f'🔴 MUDANÇA DE VOOS - ROTAS HOJE - {data_str}',
                'chart_helicopteros_hoje.png'
            )
            
            caption = f"🚨 <b>🔴 MUDANÇA DE VOOS - ATENÇÃO</b>\n\n"
            caption += f"📅 <b>ROTAS HOJE - {data_str}</b>\n\n"
            
            if add_hoje:
                caption += "<b>➕ VOOS ADICIONADOS:</b>\n"
                for sig in list(add_hoje)[:5]:
                    caption += f"  • {sig[1]} - {sig[2]} ({sig[3]})\n"
                if len(add_hoje) > 5:
                    caption += f"  ... e mais {len(add_hoje) - 5}\n"
                caption += "\n"
            
            if rem_hoje:
                caption += "<b>➖ VOOS REMOVIDOS:</b>\n"
                for sig in list(rem_hoje)[:5]:
                    caption += f"  • {sig[1]} - {sig[2]} ({sig[3]})\n"
                if len(rem_hoje) > 5:
                    caption += f"  ... e mais {len(rem_hoje) - 5}\n"
            
            notifier.send_photo(chart_path, caption)
        
        state['voos_hoje'] = voos_hoje
    
    if mudou_amanha:
        logging.info(f"Mudança detectada AMANHÃ: +{len(add_amanha)} -{len(rem_amanha)}")
        
        data_str = (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')
        
        if voos_amanha:
            chart_path = notifier._generate_single_day_diagram(
                voos_amanha,
                f'🔴 MUDANÇA DE VOOS - ROTAS AMANHÃ - {data_str}',
                'chart_helicopteros_amanha.png'
            )
            
            caption = f"🚨 <b>🔴 MUDANÇA DE VOOS - ATENÇÃO</b>\n\n"
            caption += f"📅 <b>ROTAS AMANHÃ - {data_str}</b>\n\n"
            
            if add_amanha:
                caption += "<b>➕ VOOS ADICIONADOS:</b>\n"
                for sig in list(add_amanha)[:5]:
                    caption += f"  • {sig[1]} - {sig[2]} ({sig[3]})\n"
                if len(add_amanha) > 5:
                    caption += f"  ... e mais {len(add_amanha) - 5}\n"
                caption += "\n"
            
            if rem_amanha:
                caption += "<b>➖ VOOS REMOVIDOS:</b>\n"
                for sig in list(rem_amanha)[:5]:
                    caption += f"  • {sig[1]} - {sig[2]} ({sig[3]})\n"
                if len(rem_amanha) > 5:
                    caption += f"  ... e mais {len(rem_amanha) - 5}\n"
            
            notifier.send_photo(chart_path, caption)
        
        state['voos_amanha'] = voos_amanha
    
    if mudou_hoje or mudou_amanha:
        save_diagram_state(state)
        return True
    
    logging.info("Nenhuma mudança detectada nos voos")
    return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == '--morning':
            print("Enviando diagrama matinal (voos de hoje)...")
            send_diagram_scheduled('morning')
        
        elif command == '--evening':
            print("Enviando diagrama vespertino (voos de amanhã)...")
            send_diagram_scheduled('evening')
        
        elif command == '--check':
            print("Verificando mudanças nos voos...")
            changed = check_and_send_changes()
            if changed:
                print("Mudanças detectadas e notificadas!")
            else:
                print("Nenhuma mudança detectada.")
        
        elif command == '--test':
            print("Teste: enviando ambos os diagramas...")
            send_diagram_scheduled('morning')
            send_diagram_scheduled('evening')
        
        else:
            print(f"Comando desconhecido: {command}")
            print("Uso:")
            print("  --morning  : Envia diagrama dos voos de hoje (06h)")
            print("  --evening  : Envia diagrama dos voos de amanhã (18h)")
            print("  --check    : Verifica mudanças e envia alerta se houver")
            print("  --test     : Envia ambos os diagramas (teste)")
    else:
        print("Verificando mudanças...")
        check_and_send_changes()
