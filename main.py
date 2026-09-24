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
    
    # Extrai as configurações de mapeamento enviadas pelo n8n
    col_id = payload.get("coluna_id", "lotCode")
    col_atividade = payload.get("coluna_atividade", "WODETCODE")
    col_tempo = payload.get("coluna_tempo", "RealDtStart")
    
    try:
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        df = pm4py.format_dataframe(
            df, 
            case_id=col_id, 
            activity_key=col_atividade, 
            timestamp_key=col_tempo
        )
        
        variantes = pm4py.get_variants(df)
        numero_variantes = len(variantes)
        all_case_durations = pm4py.get_all_case_durations(df)
        tempo_medio = sum(all_case_durations) / len(all_case_durations) if all_case_durations else 0
        
        # 1. Grafo de Frequência (Quantidades)
        dfg_freq, start_freq, end_freq = pm4py.discover_dfg(df)
        
        # 2. Grafo de Performance (Tempos em segundos)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df)
        
        # Juntar tudo para enviar ao n8n
        transicoes = []
        for (origem, destino), frequencia in dfg_freq.items():
            
            # Obter o dado bruto do tempo da transição
            tempo_raw = dfg_perf.get((origem, destino), 0)
            
            # CORREÇÃO: Se o pm4py devolver um dicionário de estatísticas, extrair apenas o valor da média ('mean')
            if isinstance(tempo_raw, dict):
                tempo_segundos = tempo_raw.get('mean', 0)
            else:
                tempo_segundos = tempo_raw
            
            # Garantir que a variável é convertida para float antes da divisão matemática
            tempo_horas = round(float(tempo_segundos) / 3600, 2) 
            
            transicoes.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_medio_horas": tempo_horas
            })
            
        return {
            "status": "sucesso",
            "estatisticas": {
                "total_eventos": len(df),
                "numero_variantes": numero_variantes,
                "tempo_medio_processamento_horas": round(tempo_medio / 3600, 2)
            },
            "mapa_de_fluxo": transicoes
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
    
    # Extrai as variáveis geradas pelo Agente Extrator no n8n
    maquina_alvo = str(parametros.get("maquina_alvo", ""))
    # Converte -30 (percentagem) para -0.30 (multiplicador matemático)
    modificador = float(parametros.get("modificador_percentual", 0)) / 100

    col_id = payload.get("coluna_id", "lotCode")
    col_atividade = payload.get("coluna_atividade", "WODETCODE")
    col_tempo = payload.get("coluna_tempo", "RealDtStart")

    try:
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        df = pm4py.format_dataframe(
            df, 
            case_id=col_id, 
            activity_key=col_atividade, 
            timestamp_key=col_tempo
        )
        
        dfg_freq, _, _ = pm4py.discover_dfg(df)
        dfg_perf, _, _ = pm4py.discover_performance_dfg(df)
        
        cenario_real = []
        cenario_simulado = []
        
        for (origem, destino), frequencia in dfg_freq.items():
            tempo_raw = dfg_perf.get((origem, destino), 0)
            if isinstance(tempo_raw, dict):
                tempo_segundos = tempo_raw.get('mean', 0)
            else:
                tempo_segundos = tempo_raw
                
            tempo_horas_real = round(float(tempo_segundos) / 3600, 2)
            
            # Lógica do Simulador: Se a etapa atual for a máquina alvo, aplica-se a redução/aumento de tempo
            tempo_horas_simulado = tempo_horas_real
            if str(origem) == maquina_alvo:
                # Exemplo: 7.00 horas * (1 + (-0.30)) = 7.00 * 0.70 = 4.90 horas
                tempo_horas_simulado = round(tempo_horas_real * (1 + modificador), 2)
            
            cenario_real.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_medio_horas": tempo_horas_real
            })
            
            cenario_simulado.append({
                "de": str(origem),
                "para": str(destino),
                "quantidade": frequencia,
                "tempo_medio_horas": tempo_horas_simulado
            })
            
        return {
            "status": "sucesso",
            "simulacao_aplicada": f"Tempo da etapa {maquina_alvo} alterado em {modificador*100}%",
            "cenario_real": cenario_real,
            "cenario_simulado": cenario_simulado
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": str(e)
        }