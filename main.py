import uvicorn
import pandas as pd
import pm4py
import simpy
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from io import StringIO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/analisar-fluxo")
async def analisar_processo(request: Request):
    payload = await request.json()
    dados_texto = payload.get("dados_brutos", "")
    
    col_id = payload.get("coluna_id", "lotCode")
    col_atividade = payload.get("coluna_atividade", "WODETCODE")
    col_tempo_inicio = payload.get("coluna_tempo", "RealDtStart")
    col_tempo_fim = payload.get("coluna_tempo_fim", "RealDtEnd") 
    
    try:
        df = pd.read_csv(StringIO(dados_texto), sep=None, engine='python') 
        df.columns = df.columns.str.replace('`', '').str.strip()
        df = df.replace('NULL', pd.NA)
        df = df.dropna(subset=[col_id, col_atividade, col_tempo_inicio, col_tempo_fim, 'RESOURCECODE'])
        
        # [A SOLUÇÃO IDEAL]: Identidade Composta (Máquina + Operação) igual ao Angular
        df[col_id] = df[col_id].astype(str)
        df[col_atividade] = df['RESOURCECODE'].astype(str) + "_" + df[col_atividade].astype(str)
        
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        df = df.dropna(subset=['tempo_proc_horas'])

        tempos_processamento = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()

        # O pm4py volta a usar o tempo_inicio, pois agora as máquinas estão separadas e a ordem cronológica funciona
        df_pm4py = pm4py.format_dataframe(
            df, case_id=col_id, activity_key=col_atividade, timestamp_key=col_tempo_inicio
        )
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df_pm4py)
        
        transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
            if origem == destino:
                continue
                
            tempo_raw = dfg_perf.get((origem, destino), 0)
            tempo_segundos = tempo_raw.get('mean', 0) if isinstance(tempo_raw, dict) else tempo_raw
            
            transicoes.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_transicao_com_fila_horas": round(float(tempo_segundos) / 3600, 2)
            })
            
        return {
            "status": "sucesso",
            "mapa_de_fluxo_transicoes": transicoes,
            "tempos_reais_processamento_maquinas": tempos_processamento
        }
        
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}


@app.post("/simular-what-if")
async def simular_what_if(request: Request):
    payload = await request.json()
    dados_texto = payload.get("dados_brutos", "")
    parametros = payload.get("parametros", {})
    
    maquina_alvo = str(parametros.get("maquina_alvo", ""))
    modificador = float(parametros.get("modificador_percentual", 0)) / 100

    col_id = payload.get("coluna_id", "lotCode")
    col_atividade = payload.get("coluna_atividade", "WODETCODE")
    col_tempo_inicio = payload.get("coluna_tempo", "RealDtStart")
    col_tempo_fim = payload.get("coluna_tempo_fim", "RealDtEnd")

    try:
        df = pd.read_csv(StringIO(dados_texto), sep=None, engine='python') 
        df.columns = df.columns.str.replace('`', '').str.strip()
        df = df.replace('NULL', pd.NA)
        df = df.dropna(subset=[col_id, col_atividade, col_tempo_inicio, col_tempo_fim, 'RESOURCECODE'])
        
        df[col_id] = df[col_id].astype(str)
        df[col_atividade] = df['RESOURCECODE'].astype(str) + "_" + df[col_atividade].astype(str)
        
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        df = df.dropna(subset=['tempo_proc_horas', col_tempo_inicio])
        
        df_pm4py = pm4py.format_dataframe(df, case_id=col_id, activity_key=col_atividade, timestamp_key=col_tempo_inicio)
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        
        cenario_real_transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
            if origem == destino:
                continue
            cenario_real_transicoes.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade_movimentacoes": frequencia
            })

        df_simpy = df.sort_values(by=[col_id, col_tempo_inicio])
        lotes_agrupados = df_simpy.groupby(col_id)
        
        capacidade_operacoes = {}
        for op in df[col_atividade].unique():
            df_op = df[df[col_atividade] == op]
            entradas = pd.DataFrame({'tempo': df_op[col_tempo_inicio], 'mudanca': 1})
            saidas = pd.DataFrame({'tempo': df_op[col_tempo_fim], 'mudanca': -1})
            eventos = pd.concat([entradas, saidas]).sort_values(by=['tempo', 'mudanca'])
            pico_simultaneo = eventos['mudanca'].cumsum().max()
            capacidade_operacoes[op] = max(1, int(pico_simultaneo))
        
        def rodar_fabrica_virtual(df_dados, aplicar_modificador=False):
            env = simpy.Environment()
            operacoes_unicas = df_dados[col_atividade].unique()
            
            recursos = {op: simpy.Resource(env, capacity=capacidade_operacoes[op]) for op in operacoes_unicas}
            tempos_espera = {op: [] for op in operacoes_unicas}
            
            def processar_lote(env, nome_lote, operacoes):
                for _, row in operacoes.iterrows():
                    maquina = str(row[col_atividade])
                    tempo_proc = row['tempo_proc_horas']
                    
                    # Adaptação para garantir que o modificador funciona com o nome composto (ex: se maquina_alvo for "5", afeta "MAQA_5" e "MAQB_5")
                    if aplicar_modificador and maquina.endswith(f"_{maquina_alvo}"):
                        tempo_proc = tempo_proc * (1 + modificador)
                        
                    chegada = env.now
                    with recursos[maquina].request() as req:
                        yield req 
                        espera_na_fila = env.now - chegada
                        tempos_espera[maquina].append(espera_na_fila)
                        yield env.timeout(tempo_proc)
            
            tempo_minimo = df_dados[col_tempo_inicio].min()
            
            for nome_lote, operacoes in lotes_agrupados:
                tempo_chegada = (operacoes.iloc[0][col_tempo_inicio] - tempo_minimo).total_seconds() / 3600
                def injetar(env, nome, ops, delay):
                    if delay > 0:
                        yield env.timeout(delay)
                    env.process(processar_lote(env, nome, ops))
                env.process(injetar(env, nome_lote, operacoes, tempo_chegada))
                
            env.run()
            
            resultado_filas = {}
            for m, filas in tempos_espera.items():
                filas_reais = [f for f in filas if f > 0.05] 
                qtd_total = len(filas)
                qtd_fila = len(filas_reais)
                
                media_espera = sum(filas_reais) / qtd_fila if qtd_fila > 0 else 0
                taxa_livre = ((qtd_total - qtd_fila) / qtd_total * 100) if qtd_total > 0 else 100
                
                resultado_filas[m] = {
                    "espera_horas": round(media_espera, 2),
                    "fluxo_livre_pct": round(taxa_livre, 1)
                }
            return resultado_filas

        filas_cenario_real = rodar_fabrica_virtual(df, aplicar_modificador=False)
        filas_cenario_simulado = rodar_fabrica_virtual(df, aplicar_modificador=True)
        
        tempos_processamento_real = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()
        
        comparativo_filas = []
        for maq in filas_cenario_real.keys():
            comparativo_filas.append({
                "maquina": maq,
                "tempo_processamento_unitario_horas": tempos_processamento_real.get(maq, 0),
                "tempo_medio_da_fila_REAL_horas": filas_cenario_real.get(maq, {}).get("espera_horas", 0),
                "percentual_de_lotes_em_fluxo_livre_REAL": filas_cenario_real.get(maq, {}).get("fluxo_livre_pct", 100),
                "tempo_medio_da_fila_SIMULADO_horas": filas_cenario_simulado.get(maq, {}).get("espera_horas", 0),
                "percentual_de_lotes_em_fluxo_livre_SIMULADO": filas_cenario_simulado.get(maq, {}).get("fluxo_livre_pct", 100)
            })

        return {
            "status": "sucesso",
            "simulacao_aplicada": f"Tempo de PROCESSAMENTO da máquina alvo ({maquina_alvo}) alterado em {modificador*100}%",
            "mapa_de_transicoes_quantidades": cenario_real_transicoes,
            "impacto_nas_filas_e_gargalos": comparativo_filas
        }
        
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}