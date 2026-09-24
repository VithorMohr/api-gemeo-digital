import uvicorn
import pandas as pd
import pm4py
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
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        
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