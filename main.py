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
    
    # Extrai as configurações enviadas pelo n8n, agora com a data final
    col_id = payload.get("coluna_id", "lotCode")
    col_atividade = payload.get("coluna_atividade", "WODETCODE")
    col_tempo_inicio = payload.get("coluna_tempo", "RealDtStart")
    col_tempo_fim = payload.get("coluna_tempo_fim", "RealDtEnd") 
    
    try:

        # 1. Lê os dados usando o separador original de tabulação do Excel
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        
        # 2. Converte a palavra literal "NULL" para um valor nulo real e expulsa as linhas corrompidas
        df = df.replace('NULL', pd.NA)
        df = df.dropna(subset=[col_id, col_atividade, col_tempo_inicio, col_tempo_fim])
        
        # 3. Garante que o Lote é tratado como texto
        df[col_id] = df[col_id].astype(str)
        # 1. TRATAMENTO PANDAS: Isolar o Tempo de Processamento Real (Fim - Início)
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        # Cria um dicionário com o tempo médio de máquina trabalhando (exclui fila)
        tempos_processamento = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()

        # 2. TRATAMENTO PM4PY: Mapa de Fluxo e Filas (Start to Start)
        df_pm4py = pm4py.format_dataframe(
            df, 
            case_id=col_id, 
            activity_key=col_atividade, 
            timestamp_key=col_tempo_inicio
        )
        
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df_pm4py)
        
        transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
            tempo_raw = dfg_perf.get((origem, destino), 0)
            if isinstance(tempo_raw, dict):
                tempo_segundos = tempo_raw.get('mean', 0)
            else:
                tempo_segundos = tempo_raw
            
            tempo_horas = round(float(tempo_segundos) / 3600, 2) 
            
            transicoes.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_transicao_com_fila_horas": tempo_horas
            })
            
        return {
            "status": "sucesso",
            "mapa_de_fluxo_transicoes": transicoes,
            "tempos_reais_processamento_maquinas": tempos_processamento
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": str(e)
        }

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
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        tempos_processamento_real = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()

        df_pm4py = pm4py.format_dataframe(
            df, 
            case_id=col_id, 
            activity_key=col_atividade, 
            timestamp_key=col_tempo_inicio
        )
        
        dfg_freq, _, _ = pm4py.discover_dfg(df_pm4py)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df_pm4py)
        
        cenario_real = []
        cenario_simulado = []
        
        for (origem, destino), frequencia in dfg_freq.items():
            tempo_raw = dfg_perf.get((origem, destino), 0)
            if isinstance(tempo_raw, dict):
                tempo_segundos = tempo_raw.get('mean', 0)
            else:
                tempo_segundos = tempo_raw
                
            tempo_horas_real = round(float(tempo_segundos) / 3600, 2)
            
            # Aqui no futuro entrará o SimPy. Por enquanto, mantemos a lógica matemática direta.
            tempo_horas_simulado = tempo_horas_real
            if str(origem) == maquina_alvo:
                tempo_horas_simulado = round(tempo_horas_real * (1 + modificador), 2)
            
            cenario_real.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_transicao_horas": tempo_horas_real
            })
            
            cenario_simulado.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_transicao_horas": tempo_horas_simulado
            })
            
        return {
            "status": "sucesso",
            "simulacao_aplicada": f"Tempo da etapa {maquina_alvo} alterado em {modificador*100}%",
            "tempos_reais_processamento_maquinas": tempos_processamento_real,
            "cenario_real_transicoes": cenario_real,
            "cenario_simulado_transicoes": cenario_simulado
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": str(e)
        }

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
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        df[col_tempo_inicio] = pd.to_datetime(df[col_tempo_inicio], errors='coerce')
        df[col_tempo_fim] = pd.to_datetime(df[col_tempo_fim], errors='coerce')
        
        # Calcular tempo de processamento real em horas
        df['tempo_proc_horas'] = (df[col_tempo_fim] - df[col_tempo_inicio]).dt.total_seconds() / 3600
        df = df.dropna(subset=['tempo_proc_horas', col_tempo_inicio])
        
        # Ordenar cronologicamente para simular a ordem de chegada correta
        df = df.sort_values(by=[col_id, col_tempo_inicio])
        lotes_agrupados = df.groupby(col_id)
        
        # Função do Simulador de Filas (SimPy)
        def rodar_fabrica_virtual(df_dados, aplicar_modificador=False):
            env = simpy.Environment()
            maquinas_unicas = df_dados[col_atividade].unique()
            
            # Cria 1 recurso (máquina) para cada etapa para forçar a concorrência e medir a fila
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
                        yield req # Peça entra na fila e aguarda a máquina libertar
                        
                        espera_na_fila = env.now - chegada
                        tempos_espera[maquina].append(espera_na_fila)
                        
                        yield env.timeout(tempo_proc) # Peça é processada
            
            tempo_minimo = df_dados[col_tempo_inicio].min()
            
            # Injetar os lotes na fábrica virtual no momento exato em que chegaram na vida real
            for nome_lote, operacoes in lotes_agrupados:
                tempo_chegada = (operacoes.iloc[0][col_tempo_inicio] - tempo_minimo).total_seconds() / 3600
                
                def injetar(env, nome, ops, delay):
                    if delay > 0:
                        yield env.timeout(delay)
                    env.process(processar_lote(env, nome, ops))
                    
                env.process(injetar(env, nome_lote, operacoes, tempo_chegada))
                
            env.run()
            
            # Calcular médias de fila
            resultado_filas = {}
            for m, filas in tempos_espera.items():
                resultado_filas[m] = round(sum(filas)/len(filas), 2) if filas else 0
            return resultado_filas

        # 1. Roda a simulação com a fábrica como ela é hoje
        filas_cenario_real = rodar_fabrica_virtual(df, aplicar_modificador=False)
        
        # 2. Roda a simulação matemática com a máquina alvo mais rápida/lenta
        filas_cenario_simulado = rodar_fabrica_virtual(df, aplicar_modificador=True)
        
        # 3. Compilar dados analíticos
        tempos_processamento_real = df.groupby(col_atividade)['tempo_proc_horas'].mean().round(2).to_dict()
        
        comparativo = []
        for maq in filas_cenario_real.keys():
            comparativo.append({
                "maquina": maq,
                "tempo_processamento_unitario_horas": tempos_processamento_real.get(maq, 0),
                "tempo_medio_fila_espera_REAL_horas": filas_cenario_real.get(maq, 0),
                "tempo_medio_fila_espera_SIMULADO_horas": filas_cenario_simulado.get(maq, 0)
            })

        return {
            "status": "sucesso",
            "simulacao_aplicada": f"Tempo de PROCESSAMENTO da máquina {maquina_alvo} alterado em {modificador*100}%",
            "impacto_nas_filas_e_gargalos": comparativo
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": str(e)
        }