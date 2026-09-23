import uvicorn
import pandas as pd
import pm4py
import base64
import os
import tempfile
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
        # 1. Converter texto para DataFrame
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        
        # 2. Formatar para PM4Py
        df = pm4py.format_dataframe(
            df, 
            case_id='lotCode', 
            activity_key='WODETCODE', 
            timestamp_key='RealDtStart'
        )
        
        # 3. Estatísticas base
        variantes = pm4py.get_variants(df)
        numero_variantes = len(variantes)
        all_case_durations = pm4py.get_all_case_durations(df)
        tempo_medio = sum(all_case_durations) / len(all_case_durations) if all_case_durations else 0
        
        # 4. Descobrir o Grafo de Sucessão Direta (Mapa do Processo)
        dfg, start_activities, end_activities = pm4py.discover_dfg(df)
        
        # 5. Guardar a imagem temporariamente e converter para Base64
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_filepath = tmp_file.name
            
        pm4py.save_vis_dfg(dfg, start_activities, end_activities, tmp_filepath)
        
        with open(tmp_filepath, "rb") as image_file:
            imagem_base64 = base64.b64encode(image_file.read()).decode('utf-8')
            
        os.remove(tmp_filepath) # Limpar o ficheiro do servidor
        
        return {
            "status": "sucesso",
            "mensagem": "Análise PM4Py e Geração Visual concluídas!",
            "estatisticas": {
                "total_eventos": len(df),
                "numero_variantes_processo": numero_variantes,
                "tempo_medio_processamento_segundos": round(tempo_medio, 2)
            },
            "imagem_processo_base64": imagem_base64
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": f"Erro ao processar dados: {str(e)}"
        }