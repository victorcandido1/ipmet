"""
Dashboard Interativo de Dados REVO - Salesforce
Dashboard para visualizacao de voos futuros - Fevereiro 2026
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
from utils import format_currency, format_number

try:
    from empty_legs_calculator import EmptyLegCalculator, CostCalculator, PTAXFetcher
    EMPTY_LEGS_AVAILABLE = True
except ImportError:
    EMPTY_LEGS_AVAILABLE = False

st.set_page_config(
    page_title="Dashboard REVO - Voos Fevereiro 2026",
    page_icon="helicoptero",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.8rem;
        font-weight: bold;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
        padding: 0.5rem;
        border-radius: 0.5rem;
    }
    .charter-header {
        background-color: #FEF3C7;
        color: #92400E;
        border-left: 4px solid #F59E0B;
    }
    .shuttle-header {
        background-color: #DBEAFE;
        color: #1E40AF;
        border-left: 4px solid #3B82F6;
    }
    .cost-header {
        background-color: #DCFCE7;
        color: #166534;
        border-left: 4px solid #22C55E;
    }
    .empty-header {
        background-color: #FEE2E2;
        color: #991B1B;
        border-left: 4px solid #EF4444;
    }
    .formula-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        font-family: 'Courier New', monospace;
    }
    .cost-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        padding: 1.5rem;
        color: white;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data():
    """Carrega dados processados"""
    try:
        if os.path.exists('dados_reservas.csv'):
            df = pd.read_csv('dados_reservas.csv', encoding='utf-8-sig')
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            return df
        elif os.path.exists('dados_completos.csv'):
            df = pd.read_csv('dados_completos.csv', encoding='utf-8-sig')
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            return df
        return None
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return None

HELIPONTOS = {
    'SBGR': {'nome': 'Aeroporto Guarulhos', 'lat': -23.4356, 'lon': -46.4731, 'cidade': 'Guarulhos'},
    'SIIR': {'nome': 'Brascan Century Plaza (Itaim)', 'lat': -23.5867, 'lon': -46.6803, 'cidade': 'São Paulo'},
    'SDMN': {'nome': 'Continental Tower (Cidade Jardim)', 'lat': -23.5922, 'lon': -46.6947, 'cidade': 'São Paulo'},
    'SDOF': {'nome': 'Ed. Paladio (Vila Olimpia)', 'lat': -23.5958, 'lon': -46.6856, 'cidade': 'São Paulo'},
    'SDXQ': {'nome': 'Faria Lima Int. Plaza II', 'lat': -23.5747, 'lon': -46.6894, 'cidade': 'São Paulo'},
    'SIJF': {'nome': 'Faria Lima Financial Center', 'lat': -23.5761, 'lon': -46.6889, 'cidade': 'São Paulo'},
    'SDCY': {'nome': 'Corporate Tower', 'lat': -23.5969, 'lon': -46.6919, 'cidade': 'São Paulo'},
    'SDBR': {'nome': 'Vivo REC Berrini', 'lat': -23.6028, 'lon': -46.6964, 'cidade': 'São Paulo'},
    'SNGL': {'nome': 'Fazenda Boa Vista', 'lat': -23.2667, 'lon': -47.4833, 'cidade': 'Porto Feliz'},
    'SSJN': {'nome': 'Fazenda Santa Helena', 'lat': -22.9517, 'lon': -46.5419, 'cidade': 'Bragança Paulista'},
    'SDLA': {'nome': 'Cond. Laranjeiras', 'lat': -23.2167, 'lon': -44.7167, 'cidade': 'Paraty'},
    'SJCG': {'nome': 'Iate Clube Santos (Angra)', 'lat': -23.0067, 'lon': -44.3183, 'cidade': 'Angra dos Reis'},
    'SDKR': {'nome': 'Fazenda Santo Antonio', 'lat': -22.3572, 'lon': -47.3847, 'cidade': 'Araras'},
    'SDQY': {'nome': 'Shopping Iguatemi Campinas', 'lat': -22.8267, 'lon': -47.0731, 'cidade': 'Campinas'},
    'SITP': {'nome': 'Clara Resort', 'lat': -23.6567, 'lon': -47.2231, 'cidade': 'Ibiúna'},
    'SBJH': {'nome': 'Catarina Aeroporto Executivo', 'lat': -23.4281, 'lon': -47.1653, 'cidade': 'São Roque'},
    'SDLF': {'nome': 'SBT', 'lat': -23.6328, 'lon': -46.7167, 'cidade': 'Osasco'},
    'SWWD': {'nome': 'Dom Pedro Business Park', 'lat': -23.1167, 'lon': -46.5500, 'cidade': 'Atibaia'},
    'SJWD': {'nome': 'RDP', 'lat': -22.4167, 'lon': -45.4500, 'cidade': 'Campos do Jordão'},
    'SDRR': {'nome': 'Avaré-Arandu', 'lat': -23.0983, 'lon': -48.9253, 'cidade': 'Avaré'},
    'SNJ6': {'nome': 'Heliponto Nitzan', 'lat': -23.5500, 'lon': -46.6333, 'cidade': 'São Paulo'},
    'SDFW': {'nome': 'San Paolo', 'lat': -23.5505, 'lon': -46.6333, 'cidade': 'São Paulo'},
    'SNSZ': {'nome': 'Miss Silvia Morizono', 'lat': -23.5614, 'lon': -46.6558, 'cidade': 'São Paulo'},
    'SD3I': {'nome': 'Raízen Piracicaba', 'lat': -22.7253, 'lon': -47.6492, 'cidade': 'Piracicaba'},
    'ZPFZ': {'nome': 'Porto Feliz (Privado)', 'lat': -23.2150, 'lon': -47.5250, 'cidade': 'Porto Feliz'},
}

def get_heliponto_coords(codigo):
    """Retorna coordenadas de um heliponto"""
    if codigo in HELIPONTOS:
        return HELIPONTOS[codigo]
    return None

def categorize_voo(tipo):
    """Categoriza voo como Charter ou Shuttle"""
    tipo_lower = str(tipo).lower()
    if 'charter' in tipo_lower:
        return 'Charter'
    elif 'shuttle' in tipo_lower or 'full cabin' in tipo_lower:
        return 'Shuttle'
    else:
        return 'Outros'

def get_shuttle_subcategory(tipo):
    """Subcategoriza tipos de Shuttle"""
    tipo_lower = str(tipo).lower()
    if 'full cabin' in tipo_lower:
        return 'Full Cabin'
    elif 'shuttle seat' in tipo_lower:
        return 'Shuttle Seat'
    else:
        return str(tipo)

def render_visao_geral(df):
    """Renderiza a aba de Visao Geral"""
    
    st.sidebar.header("Filtros")
    
    if 'Status' in df.columns:
        status_options = sorted(df['Status'].dropna().unique().tolist())
        selected_status = st.sidebar.multiselect("Status", options=status_options, default=status_options)
        df = df[df['Status'].isin(selected_status)]
    
    if 'Voo_Tipo' in df.columns:
        tipo_options = sorted(df['Voo_Tipo'].dropna().unique().tolist())
        selected_tipo = st.sidebar.multiselect("Tipo de Voo", options=tipo_options, default=tipo_options)
        df = df[df['Voo_Tipo'].isin(selected_tipo)]
    
    if 'Pagamento_Tipo_Registro' in df.columns:
        pag_options = sorted(df['Pagamento_Tipo_Registro'].dropna().unique().tolist())
        selected_pag = st.sidebar.multiselect("Tipo de Pagamento", options=pag_options, default=pag_options)
        df = df[df['Pagamento_Tipo_Registro'].isin(selected_pag)]
    
    st.sidebar.markdown("---")
    st.sidebar.metric("Total Reservas", len(df))
    
    if st.sidebar.button("Recarregar Dados"):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("## Indicadores Gerais - Fevereiro 2026")
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
    pax_col = 'Qtd_Passageiros_Reserva' if 'Qtd_Passageiros_Reserva' in df.columns else 'Voo_Contador_Passageiros'
    
    with kpi1:
        valor_total = df[valor_col].sum() if valor_col in df.columns else 0
        st.metric("Valor Total", format_currency(valor_total))
    
    with kpi2:
        total_reservas = len(df)
        st.metric("Total Reservas", format_number(total_reservas))
    
    with kpi3:
        total_pax = df[pax_col].sum() if pax_col in df.columns else 0
        st.metric("Total Passageiros", format_number(total_pax))
    
    with kpi4:
        voos_unicos = df['Voo_ID'].nunique() if 'Voo_ID' in df.columns else len(df)
        st.metric("Voos Programados", format_number(voos_unicos))
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Receita por Tipo de Voo")
        if 'Voo_Tipo' in df.columns:
            df_tipo = df.groupby('Voo_Tipo')[valor_col].sum().sort_values(ascending=True)
            fig = px.bar(df_tipo, orientation='h', color=df_tipo.values, color_continuous_scale='Blues')
            fig.update_layout(showlegend=False, height=350, xaxis_title="Receita (R$)", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### Distribuicao por Tipo de Pagamento")
        if 'Pagamento_Tipo_Registro' in df.columns:
            df_pag = df.groupby('Pagamento_Tipo_Registro')[valor_col].sum()
            fig = px.pie(values=df_pag.values, names=df_pag.index, color_discrete_sequence=px.colors.sequential.Blues_r)
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("### Calendario de Voos - Fevereiro 2026")
    if 'Voo_DataHora' in df.columns:
        df_cal = df[df['Voo_DataHora'].notna()].copy()
        df_cal['Data'] = df_cal['Voo_DataHora'].dt.date
        df_agg = df_cal.groupby('Data').agg({valor_col: 'sum', pax_col: 'sum'}).reset_index()
        df_agg.columns = ['Data', 'Receita', 'Passageiros']
        
        fig = px.bar(df_agg, x='Data', y='Receita', color='Receita', color_continuous_scale='Viridis')
        fig.update_layout(height=300, xaxis_title="Data", yaxis_title="Receita (R$)")
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("### Detalhamento de Reservas")
    cols_display = ['Codigo_Reserva', 'Voo_DataHora', 'Voo_Rota_Extenso', 'Voo_Tipo', 
                   'Nome_Passageiro', 'Valor_Total', 'Valor_Taxas', 'Status', 'Pagamento_Tipo_Registro']
    cols_exist = [c for c in cols_display if c in df.columns]
    st.dataframe(df[cols_exist].sort_values('Voo_DataHora'), use_container_width=True, hide_index=True)


def render_voos_futuros(df):
    """Renderiza a aba de Voos Futuros separados por Charter e Shuttle"""
    
    st.markdown("## Voos Futuros - Fevereiro 2026")
    
    df['Categoria'] = df['Voo_Tipo'].apply(categorize_voo)
    df['Subcategoria'] = df['Voo_Tipo'].apply(get_shuttle_subcategory)
    
    valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
    pax_col = 'Qtd_Passageiros_Reserva' if 'Qtd_Passageiros_Reserva' in df.columns else 'Voo_Contador_Passageiros'
    
    df_charter = df[df['Categoria'] == 'Charter'].copy()
    df_shuttle = df[df['Categoria'] == 'Shuttle'].copy()
    
    st.markdown("### Resumo Comparativo")
    
    comp1, comp2 = st.columns(2)
    
    with comp1:
        st.markdown("**Charter**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Reservas", len(df_charter))
        with c2:
            st.metric("Receita", format_currency(df_charter[valor_col].sum()))
        with c3:
            st.metric("Passageiros", format_number(df_charter[pax_col].sum()))
    
    with comp2:
        st.markdown("**Shuttle**")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("Reservas", len(df_shuttle))
        with s2:
            st.metric("Receita", format_currency(df_shuttle[valor_col].sum()))
        with s3:
            st.metric("Passageiros", format_number(df_shuttle[pax_col].sum()))
    
    comparativo = pd.DataFrame({
        'Categoria': ['Charter', 'Shuttle'],
        'Receita': [df_charter[valor_col].sum(), df_shuttle[valor_col].sum()],
        'Passageiros': [df_charter[pax_col].sum(), df_shuttle[pax_col].sum()],
        'Reservas': [len(df_charter), len(df_shuttle)]
    })
    
    col_comp1, col_comp2 = st.columns(2)
    
    with col_comp1:
        fig = px.pie(comparativo, values='Receita', names='Categoria', 
                    title='Distribuicao de Receita',
                    color='Categoria', color_discrete_map={'Charter': '#F59E0B', 'Shuttle': '#3B82F6'})
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
    
    with col_comp2:
        fig = px.bar(comparativo, x='Categoria', y=['Reservas', 'Passageiros'],
                    title='Reservas e Passageiros', barmode='group',
                    color_discrete_sequence=['#10B981', '#6366F1'])
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # CHARTER
    st.markdown('<div class="section-header charter-header">CHARTER</div>', unsafe_allow_html=True)
    
    if not df_charter.empty:
        ch1, ch2, ch3, ch4 = st.columns(4)
        with ch1:
            st.metric("Total Reservas", len(df_charter))
        with ch2:
            st.metric("Receita Total", format_currency(df_charter[valor_col].sum()))
        with ch3:
            valor_taxas = df_charter['Valor_Taxas'].sum() if 'Valor_Taxas' in df_charter.columns else 0
            st.metric("Taxas", format_currency(valor_taxas))
        with ch4:
            ticket_medio = df_charter[valor_col].mean()
            st.metric("Ticket Medio", format_currency(ticket_medio))
        
        col_ch1, col_ch2 = st.columns(2)
        
        with col_ch1:
            st.markdown("**Receita Charter por Dia**")
            if df_charter['Voo_DataHora'].notna().any():
                df_ch_dia = df_charter.groupby(df_charter['Voo_DataHora'].dt.date)[valor_col].sum().reset_index()
                df_ch_dia.columns = ['Data', 'Receita']
                fig = px.bar(df_ch_dia, x='Data', y='Receita', color='Receita', color_continuous_scale='Oranges')
                fig.update_layout(height=300, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        
        with col_ch2:
            st.markdown("**Top Rotas Charter**")
            df_ch_rota = df_charter.groupby('Voo_Rota')[valor_col].sum().sort_values(ascending=False).head(5)
            fig = px.bar(df_ch_rota, orientation='h', color=df_ch_rota.values, color_continuous_scale='Oranges')
            fig.update_layout(height=300, showlegend=False, yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("**Detalhamento Voos Charter**")
        cols_ch = ['Codigo_Reserva', 'Voo_DataHora', 'Voo_Rota_Extenso', 'Voo_Prefixo',
                  'Valor_Total', 'Valor_Taxas', 'Pagamento_Tipo_Registro', 'Nome_Passageiro']
        cols_ch_exist = [c for c in cols_ch if c in df_charter.columns]
        st.dataframe(df_charter[cols_ch_exist].sort_values('Voo_DataHora'), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum voo Charter programado")
    
    st.markdown("---")
    
    # SHUTTLE
    st.markdown('<div class="section-header shuttle-header">SHUTTLE</div>', unsafe_allow_html=True)
    
    if not df_shuttle.empty:
        sh1, sh2, sh3, sh4 = st.columns(4)
        with sh1:
            st.metric("Total Reservas", len(df_shuttle))
        with sh2:
            st.metric("Receita Total", format_currency(df_shuttle[valor_col].sum()))
        with sh3:
            st.metric("Total Passageiros", format_number(df_shuttle[pax_col].sum()))
        with sh4:
            ticket_medio_sh = df_shuttle[valor_col].mean()
            st.metric("Ticket Medio", format_currency(ticket_medio_sh))
        
        st.markdown("**Breakdown por Tipo de Shuttle**")
        df_shuttle_sub = df_shuttle.groupby('Subcategoria').agg({
            valor_col: 'sum',
            pax_col: 'sum',
            'Codigo_Reserva': 'count'
        }).reset_index()
        df_shuttle_sub.columns = ['Tipo', 'Receita', 'Passageiros', 'Reservas']
        
        sub1, sub2 = st.columns([1, 2])
        with sub1:
            st.dataframe(df_shuttle_sub, use_container_width=True, hide_index=True)
        with sub2:
            fig = px.bar(df_shuttle_sub, x='Tipo', y='Receita', color='Tipo',
                        color_discrete_sequence=['#3B82F6', '#60A5FA', '#93C5FD'])
            fig.update_layout(height=250, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        
        col_sh1, col_sh2 = st.columns(2)
        
        with col_sh1:
            st.markdown("**Receita Shuttle por Dia**")
            if df_shuttle['Voo_DataHora'].notna().any():
                df_sh_dia = df_shuttle.groupby(df_shuttle['Voo_DataHora'].dt.date)[valor_col].sum().reset_index()
                df_sh_dia.columns = ['Data', 'Receita']
                fig = px.bar(df_sh_dia, x='Data', y='Receita', color='Receita', color_continuous_scale='Blues')
                fig.update_layout(height=300, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        
        with col_sh2:
            st.markdown("**Top Rotas Shuttle**")
            df_sh_rota = df_shuttle.groupby('Voo_Rota')[valor_col].sum().sort_values(ascending=False).head(5)
            fig = px.bar(df_sh_rota, orientation='h', color=df_sh_rota.values, color_continuous_scale='Blues')
            fig.update_layout(height=300, showlegend=False, yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("**Detalhamento Voos Shuttle**")
        cols_sh = ['Codigo_Reserva', 'Voo_DataHora', 'Voo_Rota_Extenso', 'Voo_Prefixo', 'Subcategoria',
                  'Valor_Total', 'Qtd_Passageiros_Reserva', 'Nome_Passageiro', 'Pagamento_Tipo_Registro']
        cols_sh_exist = [c for c in cols_sh if c in df_shuttle.columns]
        st.dataframe(df_shuttle[cols_sh_exist].sort_values('Voo_DataHora'), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum voo Shuttle programado")
    
    st.markdown("---")
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="Baixar Dados Completos (CSV)",
        data=csv,
        file_name=f"voos_fevereiro_2026_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )


def render_mapa(df):
    """Renderiza o mapa com helipontos e rotas"""
    
    st.markdown("## Mapa de Rotas - Fevereiro 2026")
    
    valor_col = 'Valor_Total_Com_Taxas' if 'Valor_Total_Com_Taxas' in df.columns else 'Valor_Total'
    
    # Processar rotas
    rotas_data = []
    helipontos_usados = set()
    
    for _, row in df.iterrows():
        rota = str(row['Voo_Rota'])
        partes = [p.strip() for p in rota.replace('>', ' ').split()]
        
        # Pegar origem e destino (primeiro e último)
        if len(partes) >= 2:
            origem = partes[0]
            destino = partes[-1]
            
            origem_coords = get_heliponto_coords(origem)
            destino_coords = get_heliponto_coords(destino)
            
            if origem_coords and destino_coords:
                helipontos_usados.add(origem)
                helipontos_usados.add(destino)
                
                rotas_data.append({
                    'rota': rota,
                    'origem': origem,
                    'destino': destino,
                    'origem_nome': origem_coords['nome'],
                    'destino_nome': destino_coords['nome'],
                    'origem_lat': origem_coords['lat'],
                    'origem_lon': origem_coords['lon'],
                    'destino_lat': destino_coords['lat'],
                    'destino_lon': destino_coords['lon'],
                    'valor': row[valor_col],
                    'tipo': row['Voo_Tipo']
                })
    
    if not rotas_data:
        st.warning("Nenhuma rota com coordenadas encontrada")
        return
    
    df_rotas = pd.DataFrame(rotas_data)
    
    # Agregar por rota única
    df_rotas_agg = df_rotas.groupby(['rota', 'origem', 'destino', 'origem_nome', 'destino_nome',
                                     'origem_lat', 'origem_lon', 'destino_lat', 'destino_lon']).agg({
        'valor': 'sum',
        'tipo': 'count'
    }).reset_index()
    df_rotas_agg.columns = ['rota', 'origem', 'destino', 'origem_nome', 'destino_nome',
                            'origem_lat', 'origem_lon', 'destino_lat', 'destino_lon', 'receita', 'qtd_voos']
    
    # KPIs do Mapa
    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.metric("Helipontos Ativos", len(helipontos_usados))
    with kpi2:
        st.metric("Rotas Unicas", len(df_rotas_agg))
    with kpi3:
        st.metric("Receita Total Mapeada", format_currency(df_rotas_agg['receita'].sum()))
    
    # Criar dados dos helipontos para o mapa
    helipontos_list = []
    for codigo in helipontos_usados:
        h = HELIPONTOS.get(codigo)
        if h:
            # Calcular receita total do heliponto (como origem ou destino)
            receita_origem = df_rotas_agg[df_rotas_agg['origem'] == codigo]['receita'].sum()
            receita_destino = df_rotas_agg[df_rotas_agg['destino'] == codigo]['receita'].sum()
            receita_total = receita_origem + receita_destino
            
            voos_origem = df_rotas_agg[df_rotas_agg['origem'] == codigo]['qtd_voos'].sum()
            voos_destino = df_rotas_agg[df_rotas_agg['destino'] == codigo]['qtd_voos'].sum()
            
            helipontos_list.append({
                'codigo': codigo,
                'nome': h['nome'],
                'cidade': h['cidade'],
                'lat': h['lat'],
                'lon': h['lon'],
                'receita': receita_total,
                'voos': voos_origem + voos_destino,
                'texto': f"{h['nome']} ({codigo})<br>{h['cidade']}<br>R$ {receita_total:,.0f}"
            })
    
    df_helipontos = pd.DataFrame(helipontos_list)
    
    # Criar mapa
    fig = go.Figure()
    
    # Adicionar linhas das rotas
    for _, rota in df_rotas_agg.iterrows():
        # Cor baseada no valor
        cor = '#F59E0B' if 'charter' in str(df_rotas[df_rotas['rota'] == rota['rota']]['tipo'].iloc[0]).lower() else '#3B82F6'
        
        # Largura baseada na receita
        largura = max(1, min(8, rota['receita'] / 50000))
        
        fig.add_trace(go.Scattermapbox(
            mode='lines',
            lon=[rota['origem_lon'], rota['destino_lon']],
            lat=[rota['origem_lat'], rota['destino_lat']],
            line=dict(width=largura, color=cor),
            opacity=0.7,
            name=rota['rota'],
            hoverinfo='text',
            hovertext=f"{rota['origem_nome']} → {rota['destino_nome']}<br>Receita: R$ {rota['receita']:,.0f}<br>Voos: {rota['qtd_voos']}",
            showlegend=False
        ))
    
    # Adicionar pontos dos helipontos
    fig.add_trace(go.Scattermapbox(
        mode='markers+text',
        lon=df_helipontos['lon'],
        lat=df_helipontos['lat'],
        marker=dict(
            size=df_helipontos['receita'].apply(lambda x: max(15, min(40, x / 20000))),
            color=df_helipontos['receita'],
            colorscale='Viridis',
            showscale=True,
            colorbar=dict(title='Receita (R$)')
        ),
        text=df_helipontos['codigo'],
        textposition='top center',
        hoverinfo='text',
        hovertext=df_helipontos['texto'],
        name='Helipontos'
    ))
    
    # Layout do mapa
    fig.update_layout(
        mapbox=dict(
            style='carto-positron',
            center=dict(lat=-23.5, lon=-46.6),
            zoom=7
        ),
        height=600,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Legenda
    col_leg1, col_leg2 = st.columns(2)
    with col_leg1:
        st.markdown("**Legenda das Linhas:**")
        st.markdown("- <span style='color: #F59E0B;'>**Laranja**</span> = Charter", unsafe_allow_html=True)
        st.markdown("- <span style='color: #3B82F6;'>**Azul**</span> = Shuttle", unsafe_allow_html=True)
        st.markdown("- Espessura proporcional à receita")
    
    with col_leg2:
        st.markdown("**Tamanho dos Pontos:**")
        st.markdown("- Proporcional à receita total do heliponto")
        st.markdown("- Cor indica volume de receita (escala Viridis)")
    
    st.markdown("---")
    
    # Tabela de helipontos
    st.markdown("### Ranking de Helipontos por Receita")
    df_helipontos_display = df_helipontos[['codigo', 'nome', 'cidade', 'receita', 'voos']].sort_values('receita', ascending=False)
    df_helipontos_display.columns = ['Código', 'Nome', 'Cidade', 'Receita Total', 'Total Voos']
    df_helipontos_display['Receita Total'] = df_helipontos_display['Receita Total'].apply(lambda x: format_currency(x))
    st.dataframe(df_helipontos_display, use_container_width=True, hide_index=True)
    
    # Tabela de rotas
    st.markdown("### Rotas Mais Vendidas")
    df_rotas_display = df_rotas_agg[['rota', 'origem_nome', 'destino_nome', 'receita', 'qtd_voos']].sort_values('receita', ascending=False)
    df_rotas_display.columns = ['Rota', 'Origem', 'Destino', 'Receita', 'Qtd Voos']
    df_rotas_display['Receita'] = df_rotas_display['Receita'].apply(lambda x: format_currency(x))
    st.dataframe(df_rotas_display, use_container_width=True, hide_index=True)


@st.cache_data
def load_empty_legs():
    """Carrega dados de empty legs"""
    try:
        if os.path.exists('dados_empty_legs.csv'):
            df = pd.read_csv('dados_empty_legs.csv', encoding='utf-8-sig')
            df['Data_Hora'] = pd.to_datetime(df['Data_Hora'], errors='coerce')
            return df
        return None
    except Exception:
        return None


def render_custos_operacionais(df):
    """Renderiza a aba de Custos Operacionais - Custos Realizados e Projecao"""
    
    st.markdown("## Custos Operacionais - Realizados e Projecao")
    
    if not EMPTY_LEGS_AVAILABLE:
        st.error("Modulo empty_legs_calculator.py nao encontrado")
        return
    
    ptax_fetcher = PTAXFetcher()
    cost_calc = CostCalculator(ptax_fetcher)
    ptax = cost_calc.get_ptax()
    custo_var_hora = cost_calc.calcular_custo_variavel_hora(ptax)
    
    calculator = EmptyLegCalculator()
    df_empty = None
    resumo = None
    
    if calculator.carregar_voos_salesforce():
        df_empty = calculator.calcular_todos_empty_legs()
        if df_empty is not None and not df_empty.empty:
            calculator.exportar_empty_legs('dados_empty_legs.csv')
            resumo = calculator.get_resumo_empty_legs()
    
    hoje = datetime.now()
    dia_atual = hoje.day
    mes_atual = hoje.month
    ano_atual = hoje.year
    
    MESES_NOME = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril', 5: 'Maio', 6: 'Junho',
                 7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
    
    st.markdown("### Selecione o Periodo")
    
    col_periodo1, col_periodo2, col_periodo3 = st.columns([2, 2, 1])
    
    with col_periodo1:
        if 'Voo_DataHora' in df.columns:
            df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
            meses_disponiveis = df['Voo_DataHora'].dt.month.dropna().unique().tolist()
            meses_disponiveis = sorted(meses_disponiveis)
            opcoes_meses = [MESES_NOME.get(m, f'Mes {m}') for m in meses_disponiveis]
            opcoes_meses.append('Ano Completo')
        else:
            meses_disponiveis = [mes_atual]
            opcoes_meses = [MESES_NOME.get(mes_atual), 'Ano Completo']
        
        periodo_selecionado = st.selectbox('Periodo', opcoes_meses, index=len(opcoes_meses)-2 if len(opcoes_meses) > 1 else 0)
    
    with col_periodo2:
        st.metric("PTAX Atual", f"R$ {ptax:.4f}")
    
    with col_periodo3:
        st.metric("Custo/Hora", format_currency(custo_var_hora))
    
    is_ano_completo = periodo_selecionado == 'Ano Completo'
    
    if is_ano_completo:
        meses_para_processar = meses_disponiveis
    else:
        mes_selecionado = [k for k, v in MESES_NOME.items() if v == periodo_selecionado]
        meses_para_processar = mes_selecionado if mes_selecionado else [mes_atual]
    
    st.markdown("---")
    
    def dias_no_mes(mes, ano):
        if mes == 2:
            return 29 if (ano % 4 == 0 and ano % 100 != 0) or (ano % 400 == 0) else 28
        return 30 if mes in [4, 6, 9, 11] else 31
    
    def processar_mes(mes, df_dados, df_empty_dados, custo_var):
        """Processa custos de um mes especifico"""
        total_dias = dias_no_mes(mes, ano_atual)
        custos_dia = []
        
        df_mes = df_dados[(df_dados['Voo_DataHora'].dt.month == mes) & 
                          (df_dados['Voo_DataHora'].dt.year == ano_atual)].copy()
        
        if not df_mes.empty:
            df_mes['Dia'] = df_mes['Voo_DataHora'].dt.day
        
        df_empty_mes = pd.DataFrame()
        if df_empty_dados is not None and not df_empty_dados.empty:
            df_empty_dados['Data_Hora'] = pd.to_datetime(df_empty_dados['Data_Hora'], errors='coerce')
            df_empty_mes = df_empty_dados[(df_empty_dados['Data_Hora'].dt.month == mes) & 
                                           (df_empty_dados['Data_Hora'].dt.year == ano_atual)].copy()
            if not df_empty_mes.empty:
                df_empty_mes['Dia'] = df_empty_mes['Data_Hora'].dt.day
        
        for dia in range(1, total_dias + 1):
            horas_sf = 0
            custo_sf = 0
            horas_empty = 0
            custo_empty = 0
            
            if not df_mes.empty:
                df_dia = df_mes[df_mes['Dia'] == dia]
                horas_sf = len(df_dia) * 0.5
                custo_sf = horas_sf * custo_var
            
            if not df_empty_mes.empty:
                df_empty_dia = df_empty_mes[df_empty_mes['Dia'] == dia]
                if not df_empty_dia.empty:
                    horas_empty = df_empty_dia['Tempo_Voo_Horas'].sum()
                    custo_empty = df_empty_dia['Custo_BRL'].sum()
            
            if mes < mes_atual:
                status = 'Realizado'
            elif mes == mes_atual:
                status = 'Realizado' if dia < dia_atual else ('Hoje' if dia == dia_atual else 'Programado')
            else:
                status = 'Programado'
            
            custos_dia.append({
                'Mes': mes,
                'Mes_Nome': MESES_NOME.get(mes, f'Mes {mes}'),
                'Dia': dia,
                'Data': f'{dia:02d}/{mes:02d}',
                'Horas_SF': horas_sf,
                'Custo_SF': custo_sf,
                'Horas_Empty': horas_empty,
                'Custo_Empty': custo_empty,
                'Custo_Total': custo_sf + custo_empty,
                'Tipo': status
            })
        
        return custos_dia
    
    todos_custos = []
    for mes in meses_para_processar:
        todos_custos.extend(processar_mes(mes, df, df_empty, custo_var_hora))
    
    df_custos = pd.DataFrame(todos_custos)
    
    df_realizado = df_custos[df_custos['Tipo'].isin(['Realizado', 'Hoje'])]
    df_programado = df_custos[df_custos['Tipo'] == 'Programado']
    
    custo_realizado = df_realizado['Custo_Total'].sum() if not df_realizado.empty else 0
    horas_realizadas = (df_realizado['Horas_SF'].sum() + df_realizado['Horas_Empty'].sum()) if not df_realizado.empty else 0
    
    custo_programado = df_programado['Custo_Total'].sum() if not df_programado.empty else 0
    horas_programadas = (df_programado['Horas_SF'].sum() + df_programado['Horas_Empty'].sum()) if not df_programado.empty else 0
    
    custo_total = df_custos['Custo_Total'].sum()
    horas_total = df_custos['Horas_SF'].sum() + df_custos['Horas_Empty'].sum()
    
    titulo_periodo = 'Ano 2026' if is_ano_completo else periodo_selecionado
    
    st.markdown(f'<div class="section-header cost-header">CUSTOS REALIZADOS - {titulo_periodo}</div>', unsafe_allow_html=True)
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    with kpi1:
        st.metric("Custo Realizado", format_currency(custo_realizado))
    with kpi2:
        st.metric("Horas Voadas", f"{horas_realizadas:.1f}h")
    with kpi3:
        dias_realizados = len(df_realizado[df_realizado['Custo_Total'] > 0])
        st.metric("Dias com Voo", f"{dias_realizados}")
    with kpi4:
        custo_medio = custo_realizado / dias_realizados if dias_realizados > 0 else 0
        st.metric("Custo Medio/Dia", format_currency(custo_medio))
    
    st.markdown("---")
    
    st.markdown(f'<div class="section-header shuttle-header">CUSTOS PROGRAMADOS - {titulo_periodo}</div>', unsafe_allow_html=True)
    
    prog1, prog2, prog3, prog4 = st.columns(4)
    
    with prog1:
        st.metric("Custo Programado", format_currency(custo_programado))
    with prog2:
        st.metric("Horas Programadas", f"{horas_programadas:.1f}h")
    with prog3:
        dias_programados = len(df_programado[df_programado['Custo_Total'] > 0])
        st.metric("Dias com Voo", f"{dias_programados}")
    with prog4:
        voos_programados = int(df_programado['Horas_SF'].sum() / 0.5) if not df_programado.empty else 0
        st.metric("Voos Programados", f"{voos_programados}")
    
    st.markdown("---")
    
    st.markdown(f'<div class="section-header empty-header">TOTAL - {titulo_periodo}</div>', unsafe_allow_html=True)
    
    tot1, tot2, tot3, tot4 = st.columns(4)
    
    with tot1:
        st.metric("Custo Total", format_currency(custo_total))
    with tot2:
        st.metric("Horas Total", f"{horas_total:.1f}h")
    with tot3:
        total_voos = int(horas_total / 0.5) if horas_total > 0 else 0
        st.metric("Total de Voos", f"{total_voos}")
    with tot4:
        empty_legs_total = len(df_custos[df_custos['Horas_Empty'] > 0])
        st.metric("Dias c/ Empty Legs", f"{empty_legs_total}")
    
    st.markdown("---")
    
    if is_ano_completo:
        st.markdown("### Custo por Mes")
        
        df_mensal = df_custos.groupby('Mes_Nome').agg({
            'Custo_Total': 'sum',
            'Horas_SF': 'sum',
            'Horas_Empty': 'sum',
            'Tipo': lambda x: 'Realizado' if 'Realizado' in x.values else 'Programado'
        }).reset_index()
        
        df_mensal['Mes_Ordem'] = df_mensal['Mes_Nome'].map({v: k for k, v in MESES_NOME.items()})
        df_mensal = df_mensal.sort_values('Mes_Ordem')
        
        fig = go.Figure()
        
        for _, row in df_mensal.iterrows():
            cor = '#3B82F6' if row['Tipo'] == 'Realizado' else '#F59E0B'
            fig.add_trace(go.Bar(
                x=[row['Mes_Nome']],
                y=[row['Custo_Total']],
                name=row['Tipo'],
                marker_color=cor,
                showlegend=False,
                hovertemplate=f"{row['Mes_Nome']}<br>Custo: R$ %{{y:,.2f}}<extra></extra>"
            ))
        
        df_mensal['Custo_Acumulado'] = df_mensal['Custo_Total'].cumsum()
        
        fig.add_trace(go.Scatter(
            x=df_mensal['Mes_Nome'],
            y=df_mensal['Custo_Acumulado'],
            name='Acumulado',
            mode='lines+markers',
            line=dict(color='#EF4444', width=3),
            yaxis='y2',
            hovertemplate='%{x}<br>Acumulado: R$ %{y:,.2f}<extra></extra>'
        ))
        
        fig.update_layout(
            height=400,
            xaxis_title='Mes',
            yaxis_title='Custo Mensal (R$)',
            yaxis2=dict(
                title='Custo Acumulado (R$)',
                overlaying='y',
                side='right',
                showgrid=False
            ),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            hovermode='x unified'
        )
        
        mes_atual_nome = MESES_NOME.get(mes_atual, '')
        if mes_atual_nome in df_mensal['Mes_Nome'].values:
            fig.add_vline(x=mes_atual_nome, line_dash="dash", line_color="red", 
                         annotation_text="Mes Atual", annotation_position="top")
        
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### Resumo Mensal")
        df_resumo = df_mensal[['Mes_Nome', 'Horas_SF', 'Horas_Empty', 'Custo_Total', 'Tipo']].copy()
        df_resumo['Horas_Total'] = df_resumo['Horas_SF'] + df_resumo['Horas_Empty']
        df_resumo['Custo_Total'] = df_resumo['Custo_Total'].apply(lambda x: format_currency(x))
        df_resumo.columns = ['Mes', 'Horas Voos', 'Horas Empty', 'Custo', 'Status', 'Horas Total']
        df_resumo = df_resumo[['Mes', 'Status', 'Horas Voos', 'Horas Empty', 'Horas Total', 'Custo']]
        st.dataframe(df_resumo, use_container_width=True, hide_index=True)
    
    else:
        st.markdown(f"### Custo Diario - {periodo_selecionado}")
        
        fig = go.Figure()
        
        df_real = df_custos[df_custos['Tipo'].isin(['Realizado', 'Hoje'])]
        df_prog = df_custos[df_custos['Tipo'] == 'Programado']
        
        if not df_real.empty:
            fig.add_trace(go.Bar(
                x=df_real['Dia'],
                y=df_real['Custo_Total'],
                name='Realizado',
                marker_color='#3B82F6',
                hovertemplate='Dia %{x}<br>Custo Realizado: R$ %{y:,.2f}<extra></extra>'
            ))
        
        if not df_prog.empty:
            fig.add_trace(go.Bar(
                x=df_prog['Dia'],
                y=df_prog['Custo_Total'],
                name='Programado',
                marker_color='#F59E0B',
                hovertemplate='Dia %{x}<br>Custo Programado: R$ %{y:,.2f}<extra></extra>'
            ))
        
        df_custos['Custo_Acumulado'] = df_custos['Custo_Total'].cumsum()
        
        fig.add_trace(go.Scatter(
            x=df_custos['Dia'],
            y=df_custos['Custo_Acumulado'],
            name='Acumulado',
            mode='lines+markers',
            line=dict(color='#EF4444', width=2),
            yaxis='y2',
            hovertemplate='Dia %{x}<br>Acumulado: R$ %{y:,.2f}<extra></extra>'
        ))
        
        fig.update_layout(
            height=400,
            xaxis_title='Dia do Mes',
            yaxis_title='Custo Diario (R$)',
            yaxis2=dict(
                title='Custo Acumulado (R$)',
                overlaying='y',
                side='right',
                showgrid=False
            ),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            barmode='stack',
            hovermode='x unified'
        )
        
        mes_sel = meses_para_processar[0] if meses_para_processar else mes_atual
        if mes_sel == mes_atual:
            fig.add_vline(x=dia_atual + 0.5, line_dash="dash", line_color="red", 
                         annotation_text="Hoje", annotation_position="top")
        
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### Detalhamento por Dia")
        df_display = df_custos[['Dia', 'Horas_SF', 'Horas_Empty', 'Custo_Total', 'Tipo']].copy()
        df_display['Horas_Total'] = df_display['Horas_SF'] + df_display['Horas_Empty']
        df_display = df_display[df_display['Custo_Total'] > 0]
        df_display['Custo_Total'] = df_display['Custo_Total'].apply(lambda x: format_currency(x))
        df_display.columns = ['Dia', 'Horas Voos', 'Horas Empty', 'Custo', 'Status', 'Horas Total']
        df_display = df_display[['Dia', 'Status', 'Horas Voos', 'Horas Empty', 'Horas Total', 'Custo']]
        st.dataframe(df_display, use_container_width=True, hide_index=True, height=400)
    
    if df_empty is not None and not df_empty.empty:
        st.markdown("---")
        st.markdown("### Empty Legs Calculados")
        
        emp1, emp2, emp3 = st.columns(3)
        with emp1:
            st.metric("Total Empty Legs", resumo['total_empty_legs'] if resumo else 0)
        with emp2:
            st.metric("Horas Empty Legs", f"{resumo['tempo_total_horas']:.1f}h" if resumo else "0h")
        with emp3:
            st.metric("Custo Empty Legs", format_currency(resumo['custo_total_brl']) if resumo else "R$ 0,00")
        
        with st.expander("Ver detalhes dos Empty Legs"):
            cols_display = ['Tipo_Empty', 'Origem', 'Destino', 'Aeronave', 'Data_Hora', 'Tempo_Voo_Horas', 'Custo_BRL']
            cols_exist = [c for c in cols_display if c in df_empty.columns]
            df_empty_show = df_empty[cols_exist].copy()
            if 'Custo_BRL' in df_empty_show.columns:
                df_empty_show['Custo_BRL'] = df_empty_show['Custo_BRL'].apply(lambda x: format_currency(x))
            st.dataframe(df_empty_show, use_container_width=True, hide_index=True)
    
    csv_custos = df_custos.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="Baixar Custos (CSV)",
        data=csv_custos,
        file_name=f"custos_{titulo_periodo.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )


def render_resumo_mes_atual(df):
    """Renderiza o resumo do mes atual com passado e futuro"""
    
    hoje = datetime.now()
    mes_atual = hoje.month
    ano_atual = hoje.year
    dia_atual = hoje.day
    
    MESES_NOME = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril', 5: 'Maio', 6: 'Junho',
                 7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
    
    st.markdown(f"## Resumo de {MESES_NOME[mes_atual]} {ano_atual}")
    
    df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
    df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
    
    df_mes = df[(df['Voo_DataHora'].dt.month == mes_atual) & 
                (df['Voo_DataHora'].dt.year == ano_atual)].copy()
    
    if df_mes.empty:
        st.warning(f"Nenhum voo encontrado para {MESES_NOME[mes_atual]} {ano_atual}")
        return
    
    df_mes['Dia'] = df_mes['Voo_DataHora'].dt.day
    df_mes['Categoria'] = df_mes['Voo_Tipo'].apply(categorize_voo)
    
    df_passado = df_mes[df_mes['Dia'] < dia_atual]
    df_hoje = df_mes[df_mes['Dia'] == dia_atual]
    df_futuro = df_mes[df_mes['Dia'] > dia_atual]
    
    valor_col = 'Valor_Total' if 'Valor_Total' in df.columns else None
    
    st.markdown("### Visao Geral do Mes")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Voos Realizados", len(df_passado), delta=f"ate dia {dia_atual-1}")
    with col2:
        st.metric("Voos Hoje", len(df_hoje))
    with col3:
        st.metric("Voos Programados", len(df_futuro), delta=f"dia {dia_atual+1} em diante")
    with col4:
        st.metric("Total do Mes", len(df_mes))
    
    if valor_col:
        st.markdown("---")
        rec1, rec2, rec3, rec4 = st.columns(4)
        with rec1:
            st.metric("Receita Realizada", format_currency(df_passado[valor_col].sum()))
        with rec2:
            st.metric("Receita Hoje", format_currency(df_hoje[valor_col].sum()))
        with rec3:
            st.metric("Receita Programada", format_currency(df_futuro[valor_col].sum()))
        with rec4:
            st.metric("Receita Total Mes", format_currency(df_mes[valor_col].sum()))
    
    st.markdown("---")
    st.markdown("### Voos por Dia do Mes")
    
    df_por_dia = df_mes.groupby('Dia').agg({
        'Voo_Id': 'count' if 'Voo_Id' in df_mes.columns else 'size',
        valor_col: 'sum' if valor_col else 'size'
    }).reset_index()
    df_por_dia.columns = ['Dia', 'Voos', 'Receita'] if valor_col else ['Dia', 'Voos', '_']
    
    fig = go.Figure()
    
    df_realizado = df_por_dia[df_por_dia['Dia'] < dia_atual]
    df_programado = df_por_dia[df_por_dia['Dia'] >= dia_atual]
    
    if not df_realizado.empty:
        fig.add_trace(go.Bar(
            x=df_realizado['Dia'],
            y=df_realizado['Voos'],
            name='Realizado',
            marker_color='#22C55E',
            hovertemplate='Dia %{x}<br>Voos: %{y}<extra></extra>'
        ))
    
    if not df_programado.empty:
        fig.add_trace(go.Bar(
            x=df_programado['Dia'],
            y=df_programado['Voos'],
            name='Programado',
            marker_color='#3B82F6',
            hovertemplate='Dia %{x}<br>Voos: %{y}<extra></extra>'
        ))
    
    fig.add_vline(x=dia_atual, line_dash="dash", line_color="red", annotation_text="Hoje")
    
    fig.update_layout(
        height=350,
        xaxis_title='Dia',
        yaxis_title='Quantidade de Voos',
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        barmode='overlay'
    )
    st.plotly_chart(fig, use_container_width=True)
    
    col_chart, col_shuttle = st.columns(2)
    
    with col_chart:
        st.markdown("### Distribuicao por Categoria")
        df_cat = df_mes.groupby('Categoria').size().reset_index(name='Quantidade')
        fig_cat = px.pie(df_cat, values='Quantidade', names='Categoria',
                        color='Categoria', color_discrete_map={'Charter': '#F59E0B', 'Shuttle': '#3B82F6', 'Outros': '#6B7280'})
        fig_cat.update_layout(height=300)
        st.plotly_chart(fig_cat, use_container_width=True)
    
    with col_shuttle:
        st.markdown("### Por Aeronave")
        if 'Voo_Prefixo' in df_mes.columns:
            df_aero = df_mes.groupby('Voo_Prefixo').size().reset_index(name='Voos')
            fig_aero = px.bar(df_aero, x='Voo_Prefixo', y='Voos', color='Voo_Prefixo',
                             color_discrete_sequence=px.colors.qualitative.Set2)
            fig_aero.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig_aero, use_container_width=True)
    
    st.markdown("---")
    st.markdown("### Proximos Voos (Amanha e Depois)")
    
    amanha = hoje + timedelta(days=1)
    depois = hoje + timedelta(days=2)
    
    df_amanha = df_mes[df_mes['Voo_DataHora'].dt.date == amanha.date()]
    df_depois = df_mes[df_mes['Voo_DataHora'].dt.date == depois.date()]
    
    col_am, col_dep = st.columns(2)
    
    with col_am:
        st.markdown(f"**Amanha ({amanha.strftime('%d/%m')}): {len(df_amanha)} voos**")
        if not df_amanha.empty:
            cols_show = ['Voo_Numero', 'Voo_Tipo', 'Voo_Rota_ICAO', 'Voo_Prefixo']
            cols_exist = [c for c in cols_show if c in df_amanha.columns]
            if cols_exist:
                st.dataframe(df_amanha[cols_exist], hide_index=True, height=200)
    
    with col_dep:
        st.markdown(f"**Depois de Amanha ({depois.strftime('%d/%m')}): {len(df_depois)} voos**")
        if not df_depois.empty:
            cols_show = ['Voo_Numero', 'Voo_Tipo', 'Voo_Rota_ICAO', 'Voo_Prefixo']
            cols_exist = [c for c in cols_show if c in df_depois.columns]
            if cols_exist:
                st.dataframe(df_depois[cols_exist], hide_index=True, height=200)
    
    st.markdown("---")
    st.markdown("### Tabela Completa do Mes")
    cols_display = ['Voo_Numero', 'Voo_DataHora', 'Voo_Tipo', 'Voo_Rota_ICAO', 'Voo_Prefixo', 'Valor_Total', 'Status']
    cols_exist = [c for c in cols_display if c in df_mes.columns]
    st.dataframe(df_mes[cols_exist].sort_values('Voo_DataHora'), use_container_width=True, hide_index=True)


def render_resumo_ano(df):
    """Renderiza o resumo do ano completo mes a mes"""
    
    ano_atual = datetime.now().year
    mes_atual = datetime.now().month
    
    MESES_NOME = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
                 7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
    
    st.markdown(f"## Resumo Anual - {ano_atual}")
    
    df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
    df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
    
    df_ano = df[df['Voo_DataHora'].dt.year == ano_atual].copy()
    
    if df_ano.empty:
        st.warning(f"Nenhum voo encontrado para {ano_atual}")
        return
    
    df_ano['Mes'] = df_ano['Voo_DataHora'].dt.month
    df_ano['Mes_Nome'] = df_ano['Mes'].map(MESES_NOME)
    df_ano['Categoria'] = df_ano['Voo_Tipo'].apply(categorize_voo)
    
    valor_col = 'Valor_Total' if 'Valor_Total' in df.columns else None
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("Total de Voos", len(df_ano))
    with kpi2:
        if valor_col:
            st.metric("Receita Total", format_currency(df_ano[valor_col].sum()))
    with kpi3:
        meses_com_voo = df_ano['Mes'].nunique()
        st.metric("Meses com Operacao", meses_com_voo)
    with kpi4:
        media_mes = len(df_ano) / meses_com_voo if meses_com_voo > 0 else 0
        st.metric("Media Voos/Mes", f"{media_mes:.0f}")
    
    st.markdown("---")
    st.markdown("### Voos por Mes")
    
    df_mes_agg = df_ano.groupby(['Mes', 'Mes_Nome']).agg({
        'Voo_Id': 'count' if 'Voo_Id' in df_ano.columns else 'size',
        valor_col: 'sum' if valor_col else 'size'
    }).reset_index()
    df_mes_agg.columns = ['Mes', 'Mes_Nome', 'Voos', 'Receita'] if valor_col else ['Mes', 'Mes_Nome', 'Voos', '_']
    df_mes_agg = df_mes_agg.sort_values('Mes')
    
    cores = ['#22C55E' if m < mes_atual else '#3B82F6' for m in df_mes_agg['Mes']]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_mes_agg['Mes_Nome'],
        y=df_mes_agg['Voos'],
        marker_color=cores,
        text=df_mes_agg['Voos'],
        textposition='outside',
        hovertemplate='%{x}<br>Voos: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        height=400,
        xaxis_title='Mes',
        yaxis_title='Quantidade de Voos',
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)
    
    if valor_col:
        st.markdown("### Receita por Mes")
        fig_rec = go.Figure()
        fig_rec.add_trace(go.Bar(
            x=df_mes_agg['Mes_Nome'],
            y=df_mes_agg['Receita'],
            marker_color=cores,
            text=df_mes_agg['Receita'].apply(lambda x: f"R${x/1000:.0f}k"),
            textposition='outside',
            hovertemplate='%{x}<br>Receita: R$ %{y:,.2f}<extra></extra>'
        ))
        fig_rec.update_layout(height=350, xaxis_title='Mes', yaxis_title='Receita (R$)')
        st.plotly_chart(fig_rec, use_container_width=True)
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Por Categoria (Ano)")
        df_cat = df_ano.groupby('Categoria').size().reset_index(name='Voos')
        fig_cat = px.pie(df_cat, values='Voos', names='Categoria',
                        color='Categoria', color_discrete_map={'Charter': '#F59E0B', 'Shuttle': '#3B82F6', 'Outros': '#6B7280'})
        fig_cat.update_layout(height=300)
        st.plotly_chart(fig_cat, use_container_width=True)
    
    with col2:
        st.markdown("### Por Aeronave (Ano)")
        if 'Voo_Prefixo' in df_ano.columns:
            df_aero = df_ano.groupby('Voo_Prefixo').size().reset_index(name='Voos')
            fig_aero = px.pie(df_aero, values='Voos', names='Voo_Prefixo',
                             color_discrete_sequence=px.colors.qualitative.Set2)
            fig_aero.update_layout(height=300)
            st.plotly_chart(fig_aero, use_container_width=True)
    
    st.markdown("---")
    st.markdown("### Tabela Resumo Mensal")
    
    tabela_mes = df_ano.groupby(['Mes', 'Mes_Nome']).agg({
        'Voo_Id': 'count' if 'Voo_Id' in df_ano.columns else 'size',
        valor_col: 'sum' if valor_col else 'size'
    }).reset_index()
    
    if valor_col:
        tabela_mes.columns = ['Mes', 'Mes_Nome', 'Voos', 'Receita']
        tabela_mes['Receita'] = tabela_mes['Receita'].apply(lambda x: format_currency(x))
    else:
        tabela_mes.columns = ['Mes', 'Mes_Nome', 'Voos', '_']
        tabela_mes = tabela_mes[['Mes', 'Mes_Nome', 'Voos']]
    
    tabela_mes = tabela_mes.sort_values('Mes')
    tabela_mes['Status'] = tabela_mes['Mes'].apply(lambda m: 'Realizado' if m < mes_atual else ('Atual' if m == mes_atual else 'Futuro'))
    
    st.dataframe(tabela_mes[['Mes_Nome', 'Voos', 'Receita', 'Status'] if valor_col else ['Mes_Nome', 'Voos', 'Status']], 
                 use_container_width=True, hide_index=True)
    
    if EMPTY_LEGS_AVAILABLE:
        st.markdown("---")
        st.markdown("### Custos Operacionais do Ano")
        
        try:
            ptax_fetcher = PTAXFetcher()
            cost_calc = CostCalculator(ptax_fetcher)
            ptax = cost_calc.get_ptax()
            custo_var_hora = cost_calc.calcular_custo_variavel_hora(ptax)
            custo_fixo_mensal = cost_calc.calcular_custo_fixo_frota_mensal(ptax)
            
            df_empty = load_empty_legs()
            
            horas_por_mes = []
            for mes in range(1, 13):
                df_mes_v = df_ano[df_ano['Mes'] == mes]
                horas_sf = len(df_mes_v) * 0.3
                
                horas_empty = 0
                if df_empty is not None and not df_empty.empty:
                    df_empty['Data_Hora'] = pd.to_datetime(df_empty['Data_Hora'], errors='coerce')
                    df_empty_mes = df_empty[(df_empty['Data_Hora'].dt.month == mes) & 
                                            (df_empty['Data_Hora'].dt.year == ano_atual)]
                    horas_empty = df_empty_mes['Tempo_Voo_Horas'].sum() if not df_empty_mes.empty else 0
                
                custo_var = (horas_sf + horas_empty) * custo_var_hora
                custo_total = custo_fixo_mensal + custo_var if mes <= mes_atual else custo_var
                
                horas_por_mes.append({
                    'Mes': MESES_NOME[mes],
                    'Horas_Voos': round(horas_sf, 1),
                    'Horas_Empty': round(horas_empty, 1),
                    'Custo_Variavel': custo_var,
                    'Custo_Total': custo_total
                })
            
            df_custos_ano = pd.DataFrame(horas_por_mes)
            
            cust1, cust2, cust3 = st.columns(3)
            with cust1:
                custo_total_ano = df_custos_ano['Custo_Total'].sum()
                st.metric("Custo Total Ano (Est.)", format_currency(custo_total_ano))
            with cust2:
                horas_total = df_custos_ano['Horas_Voos'].sum() + df_custos_ano['Horas_Empty'].sum()
                st.metric("Horas Totais (Est.)", f"{horas_total:.1f}h")
            with cust3:
                st.metric("Custo Fixo Mensal", format_currency(custo_fixo_mensal))
            
            fig_custo = go.Figure()
            fig_custo.add_trace(go.Bar(
                x=df_custos_ano['Mes'],
                y=df_custos_ano['Custo_Total'],
                name='Custo Total',
                marker_color='#EF4444',
                text=df_custos_ano['Custo_Total'].apply(lambda x: f"R${x/1000:.0f}k"),
                textposition='outside'
            ))
            fig_custo.update_layout(height=350, xaxis_title='Mes', yaxis_title='Custo (R$)')
            st.plotly_chart(fig_custo, use_container_width=True)
            
        except Exception as e:
            st.error(f"Erro ao calcular custos: {e}")


def render_historico(df):
    """Renderiza o historico cronologico de criacao de voos no Salesforce"""
    
    st.markdown("## Historico de Criacao de Voos")
    st.markdown("Visualizacao cronologica de quando os voos foram criados no Salesforce")
    
    df['Voo_DataHora'] = pd.to_datetime(df['Voo_DataHora'], errors='coerce')
    df = df.drop_duplicates(subset=['Voo_Id']) if 'Voo_Id' in df.columns else df
    
    if 'Voo_Criado_Em' not in df.columns:
        st.warning("Campo 'Voo_Criado_Em' nao disponivel. Execute novamente: python salesforce_extractor.py --api --ano 2026")
        return
    
    df['Voo_Criado_Em'] = pd.to_datetime(df['Voo_Criado_Em'], errors='coerce')
    df = df.dropna(subset=['Voo_Criado_Em'])
    
    if df.empty:
        st.warning("Nenhum dado de criacao disponivel")
        return
    
    df['Data_Criacao'] = df['Voo_Criado_Em'].dt.date
    df['Hora_Criacao'] = df['Voo_Criado_Em'].dt.strftime('%H:%M')
    df['Semana_Criacao'] = df['Voo_Criado_Em'].dt.isocalendar().week
    df['Mes_Criacao'] = df['Voo_Criado_Em'].dt.month
    df['Ano_Criacao'] = df['Voo_Criado_Em'].dt.year
    
    valor_col = 'Valor_Total' if 'Valor_Total' in df.columns else None
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("Total de Voos", len(df))
    with kpi2:
        primeira_criacao = df['Voo_Criado_Em'].min().strftime('%d/%m/%Y')
        st.metric("Primeiro Voo Criado", primeira_criacao)
    with kpi3:
        ultima_criacao = df['Voo_Criado_Em'].max().strftime('%d/%m/%Y')
        st.metric("Ultimo Voo Criado", ultima_criacao)
    with kpi4:
        dias_operacao = (df['Voo_Criado_Em'].max() - df['Voo_Criado_Em'].min()).days
        media_dia = len(df) / dias_operacao if dias_operacao > 0 else len(df)
        st.metric("Media Voos/Dia", f"{media_dia:.1f}")
    
    st.markdown("---")
    st.markdown("### Voos Criados por Dia")
    
    df_por_dia = df.groupby('Data_Criacao').agg({
        'Voo_Id': 'count',
        valor_col: 'sum' if valor_col else 'count'
    }).reset_index()
    df_por_dia.columns = ['Data', 'Voos_Criados', 'Receita'] if valor_col else ['Data', 'Voos_Criados', '_']
    df_por_dia = df_por_dia.sort_values('Data')
    df_por_dia['Voos_Acumulados'] = df_por_dia['Voos_Criados'].cumsum()
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df_por_dia['Data'],
        y=df_por_dia['Voos_Criados'],
        name='Voos Criados',
        marker_color='#3B82F6',
        yaxis='y',
        hovertemplate='%{x}<br>Criados: %{y}<extra></extra>'
    ))
    
    fig.add_trace(go.Scatter(
        x=df_por_dia['Data'],
        y=df_por_dia['Voos_Acumulados'],
        name='Acumulado',
        line=dict(color='#22C55E', width=2),
        yaxis='y2',
        hovertemplate='%{x}<br>Total: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        height=400,
        xaxis_title='Data de Criacao',
        yaxis=dict(title='Voos por Dia', side='left'),
        yaxis2=dict(title='Acumulado', side='right', overlaying='y'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        hovermode='x unified'
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Por Semana")
        df_semana = df.groupby(['Ano_Criacao', 'Semana_Criacao']).size().reset_index(name='Voos')
        df_semana['Semana_Label'] = df_semana.apply(lambda x: f"S{int(x['Semana_Criacao']):02d}/{int(x['Ano_Criacao'])}", axis=1)
        df_semana = df_semana.sort_values(['Ano_Criacao', 'Semana_Criacao'])
        
        fig_sem = px.bar(df_semana, x='Semana_Label', y='Voos', 
                        color_discrete_sequence=['#8B5CF6'])
        fig_sem.update_layout(height=300, xaxis_title='Semana', yaxis_title='Voos Criados')
        st.plotly_chart(fig_sem, use_container_width=True)
    
    with col2:
        st.markdown("### Por Hora do Dia")
        df['Hora_Num'] = df['Voo_Criado_Em'].dt.hour
        df_hora = df.groupby('Hora_Num').size().reset_index(name='Voos')
        
        fig_hora = px.bar(df_hora, x='Hora_Num', y='Voos',
                         color_discrete_sequence=['#F59E0B'])
        fig_hora.update_layout(height=300, xaxis_title='Hora do Dia', yaxis_title='Voos Criados')
        st.plotly_chart(fig_hora, use_container_width=True)
    
    st.markdown("---")
    st.markdown("### Ultimos Voos Criados")
    
    df_recentes = df.nlargest(20, 'Voo_Criado_Em').copy()
    df_recentes['Criado_Em'] = df_recentes['Voo_Criado_Em'].dt.strftime('%d/%m/%Y %H:%M')
    df_recentes['Voo_Para'] = df_recentes['Voo_DataHora'].dt.strftime('%d/%m/%Y %H:%M')
    
    cols_display = ['Voo_Numero', 'Criado_Em', 'Voo_Para', 'Voo_Tipo', 'Voo_Rota_ICAO', 'Voo_Prefixo', 'Valor_Total']
    cols_exist = [c for c in cols_display if c in df_recentes.columns]
    
    st.dataframe(df_recentes[cols_exist], use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.markdown("### Timeline Completa")
    
    periodo = st.selectbox("Filtrar por periodo:", 
                          ["Todos", "Ultima Semana", "Ultimo Mes", "Ultimos 3 Meses"])
    
    df_filtrado = df.copy()
    hoje = datetime.now()
    
    if periodo == "Ultima Semana":
        df_filtrado = df_filtrado[df_filtrado['Voo_Criado_Em'] >= hoje - timedelta(days=7)]
    elif periodo == "Ultimo Mes":
        df_filtrado = df_filtrado[df_filtrado['Voo_Criado_Em'] >= hoje - timedelta(days=30)]
    elif periodo == "Ultimos 3 Meses":
        df_filtrado = df_filtrado[df_filtrado['Voo_Criado_Em'] >= hoje - timedelta(days=90)]
    
    df_filtrado = df_filtrado.sort_values('Voo_Criado_Em', ascending=False)
    df_filtrado['Criado_Em'] = df_filtrado['Voo_Criado_Em'].dt.strftime('%d/%m/%Y %H:%M')
    df_filtrado['Voo_Para'] = df_filtrado['Voo_DataHora'].dt.strftime('%d/%m/%Y %H:%M')
    
    cols_timeline = ['Voo_Numero', 'Criado_Em', 'Voo_Para', 'Voo_Tipo', 'Voo_Rota_ICAO', 'Voo_Prefixo', 'Valor_Total', 'Status']
    cols_exist = [c for c in cols_timeline if c in df_filtrado.columns]
    
    st.dataframe(df_filtrado[cols_exist], use_container_width=True, hide_index=True, height=400)


def main():
    st.markdown('<h1 class="main-header">Dashboard REVO - Operacao 2026</h1>', unsafe_allow_html=True)
    
    df = load_data()
    
    if df is None or df.empty:
        st.warning("Nenhum dado disponivel. Execute: python salesforce_extractor.py --api --ano 2026")
        return
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Resumo Mes Atual", 
        "Resumo Ano", 
        "Historico",
        "Visao Geral", 
        "Charter vs Shuttle", 
        "Mapa de Rotas", 
        "Custos Operacionais"
    ])
    
    with tab1:
        render_resumo_mes_atual(df.copy())
    
    with tab2:
        render_resumo_ano(df.copy())
    
    with tab3:
        render_historico(df.copy())
    
    with tab4:
        render_visao_geral(df.copy())
    
    with tab5:
        render_voos_futuros(df.copy())
    
    with tab6:
        render_mapa(df.copy())
    
    with tab7:
        render_custos_operacionais(df.copy())
    
    st.markdown("---")
    st.markdown(f"<p style='text-align: center; color: #64748B;'>Ultima atualizacao: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
