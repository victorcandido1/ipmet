"""
Script de Extração de Dados do Salesforce - REVO
Suporta extração via API ou importação de CSV exportado do Salesforce
"""

import os
from simple_salesforce import Salesforce
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime, timedelta
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('salesforce_extractor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

load_dotenv()

class SalesforceExtractor:
    def __init__(self):
        self.sf = None
    
    def connect(self):
        try:
            self.sf = Salesforce(
                username=os.getenv('SF_USERNAME'),
                password=os.getenv('SF_PASSWORD'),
                security_token=os.getenv('SF_SECURITY_TOKEN'),
                domain=os.getenv('SF_DOMAIN', 'login')
            )
            logging.info("Conexao com Salesforce estabelecida com sucesso")
            return True
        except Exception as e:
            logging.error(f"Erro ao conectar ao Salesforce: {e}")
            return False
    
    def load_from_csv(self, filepath):
        """Carrega dados de um arquivo CSV exportado do Salesforce"""
        try:
            df = pd.read_csv(filepath, sep=';', encoding='latin-1')
            
            df.columns = [
                'Status', 'Voo_Contador_Passageiros', 'Voo_DataHora', 'Valor_Total',
                'Codigo_Reserva', 'Nome_Passageiro', 'Nome_Produto', 'Voo_Rota',
                'Voo_Rota_Extenso', 'Voo_Prefixo', 'Voo_Motivo_Cancelamento',
                'Voo_Tipo', 'Pagamento_Tipo_Registro'
            ]
            
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], format='%d/%m/%Y %H:%M', errors='coerce')
            df['Valor_Total'] = df['Valor_Total'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False).astype(float)
            df['Voo_Contador_Passageiros'] = pd.to_numeric(df['Voo_Contador_Passageiros'], errors='coerce').fillna(0).astype(int)
            
            df['Data_Extracao'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            df['Voo_ID'] = df['Voo_DataHora'].astype(str) + '_' + df['Voo_Rota'].astype(str) + '_' + df['Voo_Prefixo'].astype(str)
            
            logging.info(f"CSV carregado: {len(df)} registros")
            return df
            
        except Exception as e:
            logging.error(f"Erro ao carregar CSV: {e}")
            return None
    
    def process_data(self, df):
        """Processa os dados para análise, evitando duplicação de passageiros"""
        
        df_completo = df.copy()
        
        df_voos = df[~df['Nome_Produto'].str.contains('Taxa', case=False, na=False)].copy()
        df_taxas = df[df['Nome_Produto'].str.contains('Taxa', case=False, na=False)].copy()
        
        df_reservas = df_voos.groupby(['Codigo_Reserva', 'Voo_ID', 'Voo_DataHora', 'Voo_Rota', 
                                       'Voo_Rota_Extenso', 'Voo_Prefixo', 'Voo_Tipo', 
                                       'Pagamento_Tipo_Registro', 'Status']).agg({
            'Valor_Total': 'first',
            'Nome_Passageiro': lambda x: list(x),
            'Voo_Contador_Passageiros': 'first',
            'Nome_Produto': 'first'
        }).reset_index()
        
        df_reservas['Qtd_Passageiros_Reserva'] = df_reservas['Nome_Passageiro'].apply(
            lambda x: len([p for p in x if str(p).strip()])
        )
        
        df_taxas_agg = df_taxas.groupby('Codigo_Reserva').agg({
            'Valor_Total': 'sum'
        }).reset_index()
        df_taxas_agg.columns = ['Codigo_Reserva', 'Valor_Taxas']
        
        df_reservas = df_reservas.merge(df_taxas_agg, on='Codigo_Reserva', how='left')
        df_reservas['Valor_Taxas'] = df_reservas['Valor_Taxas'].fillna(0)
        df_reservas['Valor_Total_Com_Taxas'] = df_reservas['Valor_Total'] + df_reservas['Valor_Taxas']
        
        return df_completo, df_reservas
    
    def save_processed_data(self, df_completo, df_reservas):
        """Salva os dados processados em CSVs"""
        try:
            df_completo.to_csv('dados_completos.csv', index=False, encoding='utf-8-sig')
            logging.info(f"Dados completos salvos: dados_completos.csv ({len(df_completo)} registros)")
            
            df_reservas_export = df_reservas.copy()
            df_reservas_export['Nome_Passageiro'] = df_reservas_export['Nome_Passageiro'].apply(
                lambda x: ' | '.join([str(p) for p in x if str(p).strip()])
            )
            df_reservas_export.to_csv('dados_reservas.csv', index=False, encoding='utf-8-sig')
            logging.info(f"Dados por reserva salvos: dados_reservas.csv ({len(df_reservas_export)} reservas)")
            
            return True
        except Exception as e:
            logging.error(f"Erro ao salvar CSV: {e}")
            return False
    
    def run_from_csv(self, filepath):
        """Executa o processo completo de extração a partir de CSV"""
        logging.info("=" * 60)
        logging.info("PROCESSANDO DADOS DO CSV")
        logging.info("=" * 60)
        
        df = self.load_from_csv(filepath)
        if df is None:
            return False
        
        df_completo, df_reservas = self.process_data(df)
        success = self.save_processed_data(df_completo, df_reservas)
        
        if success:
            logging.info("=" * 60)
            logging.info("PROCESSAMENTO CONCLUIDO COM SUCESSO")
            logging.info("=" * 60)
            
            valor_total = df_reservas['Valor_Total'].sum()
            valor_taxas = df_reservas['Valor_Taxas'].sum()
            total_reservas = len(df_reservas)
            total_passageiros = df_reservas['Qtd_Passageiros_Reserva'].sum()
            
            logging.info(f"Total de Reservas: {total_reservas}")
            logging.info(f"Total de Passageiros: {total_passageiros}")
            logging.info(f"Valor Total (sem taxas): R$ {valor_total:,.2f}")
            logging.info(f"Valor Taxas: R$ {valor_taxas:,.2f}")
            logging.info(f"Valor Total (com taxas): R$ {valor_total + valor_taxas:,.2f}")
        
        return success
    
    def build_query(self, incremental=False, days_back=30, data_inicio=None, data_fim=None):
        query = """
        SELECT 
            Id, Name, Status__c, ValorTotal__c, ValorPago__c, RecordType.Name,
            Oportunidade__c, Oportunidade__r.Name, Oportunidade__r.StageName,
            Voo__c, Voo__r.Name, Voo__r.Tipo__c, Voo__r.Status__c,
            Voo__r.DataHoraVoo__c, Voo__r.Rota__c, Voo__r.RotaAbreviada__c, 
            Voo__r.ContadorPassageiros__c, Voo__r.ReceitaVoo__c, Voo__r.Prefixo__c, Voo__r.Prefixo__r.Name,
            Voo__r.CreatedDate,
            CreatedDate
        FROM Servico__c 
        WHERE Voo__c != null
        """
        
        if data_inicio and data_fim:
            query += f" AND Voo__r.DataHoraVoo__c >= {data_inicio}T00:00:00Z"
            query += f" AND Voo__r.DataHoraVoo__c <= {data_fim}T23:59:59Z"
        elif incremental:
            dt_inicio = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%dT%H:%M:%SZ')
            query += f" AND CreatedDate >= {dt_inicio}"
        
        query += " ORDER BY Voo__r.DataHoraVoo__c ASC"
        return query
    
    def run_from_api(self, incremental=False, days_back=30, output_file='dados_salesforce.csv',
                     data_inicio=None, data_fim=None, return_df=False):
        """Executa extração diretamente da API do Salesforce"""
        logging.info("=" * 60)
        logging.info("EXTRAINDO DADOS DA API DO SALESFORCE")
        logging.info("=" * 60)
        
        if data_inicio:
            logging.info(f"Periodo: {data_inicio} a {data_fim}")
        elif incremental:
            logging.info(f"Modo incremental: ultimos {days_back} dias")
        else:
            logging.info("Modo: todos os registros")
        
        if not self.connect():
            return False
        
        try:
            query = self.build_query(incremental, days_back, data_inicio, data_fim)
            logging.info(f"Query: {query[:200]}...")
            result = self.sf.query_all(query)
            
            if result['totalSize'] == 0:
                logging.warning("Nenhum registro encontrado")
                return False
            
            logging.info(f"Registros encontrados: {result['totalSize']}")
            
            records = []
            for r in result['records']:
                record = {
                    'Servico_Id': r['Id'],
                    'Servico_Nome': r['Name'],
                    'Status': r['Status__c'],
                    'Valor_Total': r['ValorTotal__c'] or 0,
                    'Valor_Pago': r['ValorPago__c'] or 0,
                    'Tipo_Registro': r['RecordType']['Name'] if r.get('RecordType') else None,
                    'Voo_Id': r['Voo__c'],
                    'Voo_Numero': r['Voo__r']['Name'] if r.get('Voo__r') else None,
                    'Voo_Tipo': r['Voo__r']['Tipo__c'] if r.get('Voo__r') else None,
                    'Voo_Status': r['Voo__r']['Status__c'] if r.get('Voo__r') else None,
                    'Voo_DataHora': r['Voo__r']['DataHoraVoo__c'] if r.get('Voo__r') else None,
                    'Voo_Rota': r['Voo__r']['Rota__c'] if r.get('Voo__r') else None,
                    'Voo_Rota_ICAO': r['Voo__r']['RotaAbreviada__c'] if r.get('Voo__r') else None,
                    'Voo_Contador_Passageiros': r['Voo__r']['ContadorPassageiros__c'] if r.get('Voo__r') else 0,
                    'Voo_Prefixo': (r['Voo__r'].get('Prefixo__r', {}) or {}).get('Name') or r['Voo__r'].get('Prefixo__c') if r.get('Voo__r') else None,
                    'Voo_Criado_Em': r['Voo__r']['CreatedDate'] if r.get('Voo__r') else None,
                    'Codigo_Reserva': r['Name'],
                }
                records.append(record)
            
            df = pd.DataFrame(records)
            
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            df['Data_Extracao'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if output_file:
                df.to_csv(output_file, index=False, encoding='utf-8-sig')
                logging.info(f"Dados salvos: {output_file} ({len(df)} registros)")

            # Mantido por compatibilidade com outros scripts.
            if output_file:
                df.to_csv('dados_reservas.csv', index=False, encoding='utf-8-sig')
                logging.info(f"Dados reservas salvos: dados_reservas.csv")
            
            if not df.empty:
                logging.info("=" * 60)
                logging.info("RESUMO DA EXTRACAO")
                logging.info("=" * 60)
                logging.info(f"Total de registros: {len(df)}")
                logging.info(f"Valor Total: R$ {df['Valor_Total'].sum():,.2f}")
                
                meses = df['Voo_DataHora'].dt.to_period('M').value_counts().sort_index()
                logging.info("Registros por mes:")
                for mes, qtd in meses.items():
                    logging.info(f"  {mes}: {qtd} registros")
            
            return df if return_df else True
            
        except Exception as e:
            logging.error(f"Erro: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None if return_df else False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Extrator de Dados do Salesforce - REVO')
    parser.add_argument('--csv', type=str, help='Caminho para CSV exportado do Salesforce')
    parser.add_argument('--api', action='store_true', help='Extrair diretamente da API')
    parser.add_argument('--incremental', action='store_true', help='Extracao incremental')
    parser.add_argument('--days', type=int, default=30, help='Dias para extracao incremental')
    parser.add_argument('--data-inicio', type=str, help='Data inicio (YYYY-MM-DD), ex: 2026-01-01')
    parser.add_argument('--data-fim', type=str, help='Data fim (YYYY-MM-DD), ex: 2026-02-28')
    parser.add_argument('--ano', type=int, help='Extrair ano completo (ex: 2026)')
    parser.add_argument('--mes', type=int, help='Extrair mes especifico (1-12), usar com --ano')
    parser.add_argument('--output', type=str, default='dados_salesforce.csv', help='Arquivo de saida')
    parser.add_argument('--empty-legs', action='store_true', help='Calcular empty legs apos extracao')
    
    args = parser.parse_args()
    
    extractor = SalesforceExtractor()
    success = False
    
    data_inicio = args.data_inicio
    data_fim = args.data_fim
    
    if args.ano:
        if args.mes:
            import calendar
            ultimo_dia = calendar.monthrange(args.ano, args.mes)[1]
            data_inicio = f"{args.ano}-{args.mes:02d}-01"
            data_fim = f"{args.ano}-{args.mes:02d}-{ultimo_dia}"
        else:
            data_inicio = f"{args.ano}-01-01"
            data_fim = f"{args.ano}-12-31"
    
    if args.csv:
        success = extractor.run_from_csv(args.csv)
    elif args.api:
        success = extractor.run_from_api(
            incremental=args.incremental, 
            days_back=args.days, 
            output_file=args.output,
            data_inicio=data_inicio,
            data_fim=data_fim
        )
    else:
        print("Use --csv <arquivo> ou --api para extrair dados")
        print("")
        print("Exemplos:")
        print("  python salesforce_extractor.py --api --ano 2026")
        print("  python salesforce_extractor.py --api --ano 2026 --mes 1")
        print("  python salesforce_extractor.py --api --data-inicio 2026-01-01 --data-fim 2026-02-28")
        print("  python salesforce_extractor.py --api --incremental --days 60")
        return
    
    if success and getattr(args, 'empty_legs', False):
        try:
            from empty_legs_calculator import EmptyLegCalculator
            logging.info("Calculando Empty Legs...")
            calculator = EmptyLegCalculator()
            df_empty = calculator.calcular_todos_empty_legs()
            if df_empty is not None and not df_empty.empty:
                calculator.exportar_empty_legs('dados_empty_legs.csv')
                resumo = calculator.get_resumo_empty_legs()
                logging.info(f"Empty Legs gerados: {resumo['total_empty_legs']}")
                logging.info(f"Tempo total: {resumo['tempo_total_horas']:.2f}h")
                logging.info(f"Custo total: R$ {resumo['custo_total_brl']:,.2f}")
        except ImportError:
            logging.warning("Modulo empty_legs_calculator.py nao encontrado")
        except Exception as e:
            logging.error(f"Erro ao calcular empty legs: {e}")


if __name__ == "__main__":
    main()
