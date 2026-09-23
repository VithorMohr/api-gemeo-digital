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
    
    try:
        # 1. Converter e Formatar
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        df = pm4py.format_dataframe(
            df, 
            case_id='lotCode', 
            activity_key='WODETCODE', 
            timestamp_key='RealDtStart'
        )
        
        # 2. Estatísticas base
        variantes = pm4py.get_variants(df)
        numero_variantes = len(variantes)
        all_case_durations = pm4py.get_all_case_durations(df)
        tempo_medio = sum(all_case_durations) / len(all_case_durations) if all_case_durations else 0
        
        # 3. Extrair o Grafo (Sem tentar desenhar a imagem)
        dfg, start_activities, end_activities = pm4py.discover_dfg(df)
        
        # O DFG do PM4Py devolve um dicionário com tuplos como chaves: ('Atividade A', 'Atividade B'): Frequencia
        # Precisamos de converter isto para texto legível para o JSON do n8n
        caminhos_formatados = []
        for (origem, destino), frequencia in dfg.items():
            caminhos_formatados.append({
                "de": origem,
                "para": destino,
                "quantidade_passagens": frequencia
            })
        
        return {
            "status": "sucesso",
            "estatisticas": {
                "total_eventos": len(df),
                "numero_variantes_processo": numero_variantes,
                "tempo_medio_processamento_segundos": round(tempo_medio, 2)
            },
            "mapa_de_fluxo": caminhos_formatados
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": f"Erro ao processar dados: {str(e)}"
        }