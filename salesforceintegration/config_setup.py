"""
Script de Configuração Segura
Cria o arquivo .env de forma interativa e segura
"""

import os
import getpass
from pathlib import Path

def create_env_file():
    """Cria arquivo .env de forma interativa"""
    print("\n" + "=" * 80)
    print("CONFIGURAÇÃO DE CREDENCIAIS DO SALESFORCE")
    print("=" * 80)
    print("\nEste script irá criar um arquivo .env com suas credenciais.")
    print("⚠️  IMPORTANTE: Nunca compartilhe este arquivo ou faça commit dele no Git!\n")
    
    # Verificar se já existe .env
    if os.path.exists('.env'):
        response = input("⚠️  Arquivo .env já existe. Deseja sobrescrever? (s/N): ").lower()
        if response not in ['s', 'sim', 'y', 'yes']:
            print("❌ Operação cancelada.")
            return
    
    # Coletar credenciais
    print("\n📝 Digite suas credenciais do Salesforce:\n")
    
    username = input("Username (email): ").strip()
    password = getpass.getpass("Password: ")
    
    print("\n💡 O Security Token é enviado por email quando você reseta no Salesforce.")
    print("   Vá em: Setup > My Personal Information > Reset My Security Token")
    security_token = input("Security Token: ").strip()
    
    print("\n🔑 As chaves do Connected App (Consumer Key e Secret):")
    consumer_key = input("Consumer Key (Connected App): ").strip()
    if not consumer_key:
        raise ValueError("Consumer Key é obrigatório")
    
    consumer_secret = input("Consumer Secret (Connected App): ").strip()
    if not consumer_secret:
        raise ValueError("Consumer Secret é obrigatório")
    
    domain = input("Domain (login/test) [padrão: login]: ").strip() or "login"
    
    # Criar conteúdo do .env
    env_content = f"""# Credenciais do Salesforce
# ⚠️ NUNCA faça commit deste arquivo no Git!

# Credenciais de Login
SF_USERNAME={username}
SF_PASSWORD={password}
SF_SECURITY_TOKEN={security_token}

# Credenciais do Connected App
SF_CONSUMER_KEY={consumer_key}
SF_CONSUMER_SECRET={consumer_secret}

# Domain (use 'test' para sandbox)
SF_DOMAIN={domain}
"""
    
    # Salvar arquivo
    try:
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print("\n" + "=" * 80)
        print("✅ Arquivo .env criado com sucesso!")
        print("=" * 80)
        print("\n📁 Localização:", os.path.abspath('.env'))
        print("\n🔒 Segurança:")
        print("   ✓ Arquivo adicionado ao .gitignore")
        print("   ✓ Não será incluído em commits do Git")
        print("\n📝 Próximos passos:")
        print("   1. Execute: python explore_salesforce.py (para mapear campos)")
        print("   2. Execute: python salesforce_extractor.py (para extrair dados)")
        print("   3. Execute: streamlit run app.py (para visualizar dashboard)")
        
    except Exception as e:
        print(f"\n❌ Erro ao criar arquivo .env: {e}")

def verify_env_file():
    """Verifica se o arquivo .env está configurado corretamente"""
    if not os.path.exists('.env'):
        print("❌ Arquivo .env não encontrado!")
        print("   Execute 'python config_setup.py' para criar o arquivo.")
        return False
    
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = [
        'SF_USERNAME',
        'SF_PASSWORD',
        'SF_SECURITY_TOKEN'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Variáveis faltando no .env:")
        for var in missing_vars:
            print(f"   - {var}")
        return False
    
    print("✅ Arquivo .env está configurado corretamente!")
    return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Configuração segura de credenciais')
    parser.add_argument('--verify', action='store_true', 
                       help='Verifica se o .env está configurado corretamente')
    
    args = parser.parse_args()
    
    if args.verify:
        verify_env_file()
    else:
        create_env_file()

if __name__ == "__main__":
    main()
