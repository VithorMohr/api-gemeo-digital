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
        # 1. Leitura Robusta: Ignora formatações erradas e limpa crases/espaços
        df = pd.read_csv(StringIO(dados_texto), sep=None, engine='python') 
        df.columns = df.columns.str.replace('`', '').str.strip()
        df = df.replace('NULL', pd.NA)
        df = df.dropna(subset=[col_id, col_atividade, col_tempo_inicio, col_tempo_fim])
        
        # 2. Forçar Tipagem para Texto (A Correção)
        df[col_id] = df[col_id].astype(str)
        df[col_atividade] = df[col_atividade].astype(str)
        
        # 3. Tratamento de Datas e Cálculo de Processamento
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        tempos_processamento = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()

        # 4. Process Mining: Mapa de Fluxo
        df_pm4py = pm4py.format_dataframe(
            df, case_id=col_id, activity_key=col_atividade, timestamp_key=col_tempo_inicio
        )
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df_pm4py)
        
        transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
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
        # 1. Leitura Robusta
        df = pd.read_csv(StringIO(dados_texto), sep=None, engine='python') 
        df.columns = df.columns.str.replace('`', '').str.strip()
        df = df.replace('NULL', pd.NA)
        df = df.dropna(subset=[col_id, col_atividade, col_tempo_inicio, col_tempo_fim])
        df[col_id] = df[col_id].astype(str)
        
        # 2. Datas e Processamento
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        df = df.dropna(subset=['tempo_proc_horas', col_tempo_inicio])
        
        # 3. Mapa de Transições (Para a IA saber de onde a peça vem e para onde vai)
        df_pm4py = pm4py.format_dataframe(df, case_id=col_id, activity_key=col_atividade, timestamp_key=col_tempo_inicio)
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        
        cenario_real_transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
            cenario_real_transicoes.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade_movimentacoes": frequencia
            })

        # 4. SIMPY: Simulador de Filas
        df_simpy = df.sort_values(by=[col_id, col_tempo_inicio])
        lotes_agrupados = df_simpy.groupby(col_id)
        
        def rodar_fabrica_virtual(df_dados, aplicar_modificador=False):
            env = simpy.Environment()
            maquinas_unicas = df_dados[col_atividade].unique()
            recursos = {m: simpy.Resource(env, capacity=1) for m in maquinas_unicas}
            tempos_espera = {m: [] for m in maquinas_unicas}
            
            def processar_lote(env, nome_lote, operacoes):
                for _, row in operacoes.iterrows():
                    maquina = str(row[col_atividade])
                    tempo_proc = row['tempo_proc_horas']
                    
                    if aplicar_modificador and maquina == maquina_alvo:
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
                resultado_filas[m] = round(sum(filas)/len(filas), 2) if filas else 0
            return resultado_filas

        filas_cenario_real = rodar_fabrica_virtual(df, aplicar_modificador=False)
        filas_cenario_simulado = rodar_fabrica_virtual(df, aplicar_modificador=True)
        
        tempos_processamento_real = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()
        
        comparativo_filas = []
        for maq in filas_cenario_real.keys():
            comparativo_filas.append({
                "maquina": maq,
                "tempo_processamento_unitario_horas": tempos_processamento_real.get(maq, 0),
                "tempo_medio_fila_espera_antes_da_maquina_REAL_horas": filas_cenario_real.get(maq, 0),
                "tempo_medio_fila_espera_antes_da_maquina_SIMULADO_horas": filas_cenario_simulado.get(maq, 0)
            })

        # 5. Retorno Consolidado
        return {
            "status": "sucesso",
            "simulacao_aplicada": f"Tempo de PROCESSAMENTO da máquina {maquina_alvo} alterado em {modificador*100}%",
            "mapa_de_transicoes_quantidades": cenario_real_transicoes,
            "impacto_nas_filas_e_gargalos": comparativo_filas
        }
        
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}