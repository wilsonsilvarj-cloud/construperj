# app.py
# Consultor Virtual SGI - Construperj
# Interface Web em Streamlit com busca em documentos e resposta via ChatGPT/OpenAI

import os
import re
import io
import json
import shutil
import hashlib
import base64
from pathlib import Path
from datetime import datetime

import streamlit as st

# Importações opcionais para não derrubar o app no Streamlit Cloud
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# =========================================================
# 1. CONFIGURAÇÕES PRINCIPAIS
# =========================================================

APP_TITLE = "Consultor Virtual SGI"
EMPRESA = "Construperj Construtora"

# Caminho principal do aplicativo.
# No Streamlit Cloud/GitHub, os documentos ficam junto do APP.py ou em subpastas do repositório.
BASE_DIR = Path(__file__).resolve().parent

PASTAS_DOCUMENTOS = {
    "Documentos na raiz do repositório": BASE_DIR,
    "Formulários - Segurança do Trabalho": BASE_DIR / r"Documentos SGI/Formulários/02. Segurança do Trabalho",
    "Procedimentos - Saúde do Trabalho": BASE_DIR / r"Documentos SGI/Procedimentos/Procedimentos de Saude do trabalho",
    "Procedimentos - Segurança do Trabalho": BASE_DIR / r"Documentos SGI/Procedimentos/Procedimentos de Segurança do Trabalho",
}

# Coloque o logo na mesma pasta do app.py com o nome abaixo
LOGO_PATH = BASE_DIR / "logo_construperj.png"

# Modelo OpenAI
OPENAI_MODEL = "gpt-4.1-mini"

# Limites de segurança para evitar envio excessivo de texto
MAX_CHARS_POR_PDF = 80_000
MAX_CHARS_CONTEXTO = 180_000
TOP_K_DOCUMENTOS = 8

# =========================================================
# 2. CONFIGURAÇÃO DA PÁGINA
# =========================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# 3. ESTILO VISUAL
# =========================================================

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(135deg, #f7f9fc 0%, #eef3f8 45%, #ffffff 100%);
    }

    .main-header {
        background: linear-gradient(135deg, #002b5c 0%, #00417d 55%, #0b8f3a 100%);
        padding: 28px 32px;
        border-radius: 22px;
        color: white;
        box-shadow: 0 12px 35px rgba(0, 43, 92, 0.20);
        margin-bottom: 24px;
    }

    .main-header h1 {
        font-size: 2.2rem;
        margin-bottom: 8px;
        font-weight: 800;
        letter-spacing: -0.5px;
    }

    .main-header p {
        font-size: 1.03rem;
        opacity: 0.94;
        margin: 0;
    }

    .metric-card {
        background: white;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid #e5e9f0;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
        text-align: center;
    }

    .metric-card h3 {
        color: #002b5c;
        margin: 0;
        font-size: 1.6rem;
    }

    .metric-card p {
        color: #667085;
        margin: 4px 0 0 0;
        font-size: 0.92rem;
    }

    .doc-card {
        background: white;
        padding: 16px 18px;
        border-radius: 16px;
        border-left: 5px solid #0b8f3a;
        box-shadow: 0 7px 18px rgba(15, 23, 42, 0.06);
        margin-bottom: 12px;
    }

    .doc-title {
        color: #002b5c;
        font-weight: 750;
        margin-bottom: 4px;
    }

    .doc-meta {
        color: #667085;
        font-size: 0.88rem;
    }

    .small-info {
        font-size: 0.88rem;
        color: #667085;
    }

    div[data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e5e9f0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# 4. FUNÇÕES AUXILIARES
# =========================================================

def normalizar_texto(texto: str) -> str:
    texto = texto.lower()
    texto = re.sub(r"[^a-záàâãéèêíïóôõöúçñ0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def listar_arquivos_documentos():
    extensoes = [".pdf", ".docx", ".xlsx", ".xls", ".doc", ".txt"]
    arquivos = []
    caminhos_adicionados = set()

    for categoria, pasta in PASTAS_DOCUMENTOS.items():
        if not pasta.exists():
            continue

        for arquivo in pasta.rglob("*"):
            if arquivo.is_file() and arquivo.suffix.lower() in extensoes:
                caminho_resolvido = arquivo.resolve()
                if caminho_resolvido in caminhos_adicionados:
                    continue
                caminhos_adicionados.add(caminho_resolvido)

                arquivos.append(
                    {
                        "categoria": categoria,
                        "nome": arquivo.name,
                        "caminho": arquivo,
                        "extensao": arquivo.suffix.lower(),
                        "tamanho_mb": arquivo.stat().st_size / (1024 * 1024),
                    }
                )

    return arquivos


@st.cache_data(show_spinner="Lendo documentos PDF...")
def extrair_texto_pdf(caminho_str: str, max_chars: int = MAX_CHARS_POR_PDF):
    caminho = Path(caminho_str)
    texto_total = []
    paginas_lidas = 0

    try:
        if PdfReader is None:
            return "", 0, "Biblioteca pypdf não instalada. Verifique o requirements.txt."

        reader = PdfReader(str(caminho))
        for page in reader.pages:
            if sum(len(t) for t in texto_total) >= max_chars:
                break
            texto = page.extract_text() or ""
            if texto.strip():
                texto_total.append(texto)
            paginas_lidas += 1

        texto_final = "\n".join(texto_total)[:max_chars]
        return texto_final, paginas_lidas, None

    except Exception as e:
        return "", 0, str(e)


@st.cache_data(show_spinner="Indexando documentos...")
def carregar_base_documental():
    arquivos = listar_arquivos_documentos()
    base = []

    for item in arquivos:
        texto = ""
        paginas = 0
        erro = None

        if item["extensao"] == ".pdf":
            texto, paginas, erro = extrair_texto_pdf(str(item["caminho"]))
        else:
            # Arquivos não PDF entram no catálogo e podem ser baixados.
            # Para leitura interna, recomenda-se converter DOCX/XLSX para PDF ou TXT.
            texto = f"Documento disponível no catálogo: {item['nome']}"

        base.append(
            {
                **item,
                "texto": texto,
                "texto_normalizado": normalizar_texto(item["nome"] + " " + item["categoria"] + " " + texto[:5000]),
                "paginas": paginas,
                "erro": erro,
            }
        )

    return base


def pontuar_documento(pergunta: str, doc: dict) -> int:
    pergunta_norm = normalizar_texto(pergunta)
    termos = [t for t in pergunta_norm.split() if len(t) >= 3]

    score = 0
    texto = doc["texto_normalizado"]

    for termo in termos:
        if termo in texto:
            score += 1
        if termo in normalizar_texto(doc["nome"]):
            score += 3
        if termo in normalizar_texto(doc["categoria"]):
            score += 2

    # Reforços por palavras frequentes em SST
    sinonimos = {
        "altura": ["nr 35", "trabalho em altura", "queda"],
        "eletricidade": ["nr 10", "elétrica", "eletrico", "eletricista"],
        "andaime": ["andaimes", "checklist", "check-list"],
        "epi": ["equipamento de proteção", "proteção individual"],
        "procedimento": ["procedimento", "norma", "instrução"],
        "formulário": ["formulário", "formulario", "checklist", "check-list"],
    }

    for chave, lista in sinonimos.items():
        if chave in pergunta_norm:
            for termo in lista:
                if termo in texto:
                    score += 5

    return score


def buscar_documentos_relevantes(pergunta: str, base: list, top_k: int = TOP_K_DOCUMENTOS):
    ranqueados = []
    for doc in base:
        score = pontuar_documento(pergunta, doc)
        if score > 0:
            ranqueados.append((score, doc))

    ranqueados.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in ranqueados[:top_k]]


def montar_contexto(docs: list):
    partes = []
    total = 0

    for i, doc in enumerate(docs, 1):
        trecho = doc["texto"][:40_000]
        bloco = f"""
[DOCUMENTO {i}]
Nome: {doc['nome']}
Categoria: {doc['categoria']}
Caminho: {doc['caminho']}
Conteúdo extraído:
{trecho}
"""
        if total + len(bloco) > MAX_CHARS_CONTEXTO:
            break
        partes.append(bloco)
        total += len(bloco)

    return "\n\n".join(partes)


def responder_com_ia(pergunta: str, docs: list):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "⚠️ A chave OPENAI_API_KEY não foi encontrada. Configure a variável de ambiente antes de usar a IA."

    if OpenAI is None:
        return "⚠️ A biblioteca openai não foi carregada. Verifique se o arquivo requirements.txt contém: openai"

    contexto = montar_contexto(docs)
    client = OpenAI(api_key=api_key)

    system_prompt = """
Você é um Consultor Virtual de SGI, Segurança e Saúde do Trabalho da Construperj.
Responda exclusivamente com base nos documentos fornecidos no contexto.

Regras obrigatórias:
1. Responda em português do Brasil.
2. Use linguagem técnica, clara e objetiva.
3. Não invente informação que não esteja nos documentos.
4. Quando a resposta estiver baseada em um documento, cite o nome do documento.
5. Se a informação não estiver nos documentos enviados, diga claramente que não localizou essa informação na base documental.
6. Quando o usuário pedir normas, procedimentos, formulários ou check-lists, liste os documentos mais prováveis e explique a finalidade de cada um.
7. Quando possível, indique que o arquivo está disponível para download na interface.
8. Mesmo que a pergunta tenha erros de português, interprete a intenção do usuário e responda de forma clara.
"""

    user_prompt = f"""
Pergunta do funcionário:
{pergunta}

Documentos recuperados da base documental:
{contexto}
"""

    try:
        resposta = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resposta.choices[0].message.content

    except Exception as e:
        return f"⚠️ Erro ao consultar a IA: {e}"


def gerar_audio_ia(texto: str):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "⚠️ A chave OPENAI_API_KEY não foi encontrada para gerar o áudio."

    if OpenAI is None:
        return None, "⚠️ A biblioteca openai não foi carregada. Verifique se o arquivo requirements.txt contém: openai"

    try:
        client = OpenAI(api_key=api_key)
        resposta_audio = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="onyx",
            input=texto[:4000],
        )
        return resposta_audio.content, None

    except Exception as e:
        return None, f"⚠️ Erro ao gerar áudio: {e}"


def exibir_audio_automatico(audio_bytes: bytes):
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    st.markdown(
        f"""
        <audio autoplay controls>
            <source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3">
        </audio>
        """,
        unsafe_allow_html=True,
    )


def transcrever_audio_ia(audio_file):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "", "⚠️ A chave OPENAI_API_KEY não foi encontrada para transcrever o áudio."

    if OpenAI is None:
        return "", "⚠️ A biblioteca openai não foi carregada. Verifique se o arquivo requirements.txt contém: openai"

    try:
        client = OpenAI(api_key=api_key)
        audio_bytes = audio_file.getvalue()
        audio_buffer = io.BytesIO(audio_bytes)
        audio_buffer.name = "pergunta.wav"

        transcricao = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_buffer,
            language="pt",
        )

        return transcricao.text, None

    except Exception as e:
        return "", f"⚠️ Erro ao transcrever áudio: {e}"


def botao_download_arquivo(doc: dict, key_prefix: str):
    caminho = Path(doc["caminho"])
    if caminho.exists():
        with open(caminho, "rb") as f:
            st.download_button(
                label=f"⬇️ Baixar: {doc['nome']}",
                data=f.read(),
                file_name=doc["nome"],
                mime="application/octet-stream",
                key=f"download_{key_prefix}_{hashlib.md5(str(caminho).encode()).hexdigest()}",
            )

# =========================================================
# 5. SIDEBAR
# =========================================================

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    else:
        st.info("Coloque o arquivo do logo como: logo_construperj.png")

    st.markdown(f"### {EMPRESA}")
    st.markdown("**Sistema de consulta inteligente de documentos SGI**")
    st.divider()

    st.markdown("### Pastas monitoradas")
    for categoria, pasta in PASTAS_DOCUMENTOS.items():
        existe = "✅" if pasta.exists() else "⚠️"
        st.caption(f"{existe} {categoria}")

    st.divider()

    if st.button("🔄 Atualizar base documental", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption("A base é lida a partir das pastas locais configuradas no código.")

# =========================================================
# 6. CABEÇALHO
# =========================================================

st.markdown(
    f"""
    <div class="main-header">
        <h1>{APP_TITLE}</h1>
        <p>Assistente inteligente para consulta de procedimentos, normas, formulários e check-lists de Segurança e Saúde do Trabalho.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# 7. CARREGAMENTO DA BASE
# =========================================================

base = carregar_base_documental()

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"<div class='metric-card'><h3>{len(base)}</h3><p>Documentos encontrados</p></div>", unsafe_allow_html=True)
with col2:
    pdfs = len([d for d in base if d["extensao"] == ".pdf"])
    st.markdown(f"<div class='metric-card'><h3>{pdfs}</h3><p>PDFs indexados</p></div>", unsafe_allow_html=True)
with col3:
    chars = sum(len(d.get("texto", "")) for d in base)
    st.markdown(f"<div class='metric-card'><h3>{chars:,}</h3><p>Caracteres extraídos</p></div>".replace(",", "."), unsafe_allow_html=True)

st.write("")

# =========================================================
# 8. ABAS PRINCIPAIS
# =========================================================

tab_chat, tab_catalogo, tab_config = st.tabs(["💬 Consultor Virtual", "📁 Catálogo de Documentos", "⚙️ Configurações"])

# ----------------------------
# ABA 1: CHAT
# ----------------------------
with tab_chat:
    st.subheader("Faça uma pergunta sobre procedimentos, normas, formulários ou check-lists")

    audio_pergunta = st.audio_input("Opcional: fale sua pergunta por voz")

    if audio_pergunta is not None:
        audio_hash = hashlib.md5(audio_pergunta.getvalue()).hexdigest()
        if st.session_state.get("audio_pergunta_hash") != audio_hash:
            with st.spinner("Transcrevendo sua pergunta por voz..."):
                texto_transcrito, erro_transcricao = transcrever_audio_ia(audio_pergunta)

            if erro_transcricao:
                st.warning(erro_transcricao)
            elif texto_transcrito:
                st.session_state["pergunta_digitada"] = texto_transcrito
                st.session_state["audio_pergunta_hash"] = audio_hash

    pergunta = st.text_area(
        "Digite sua solicitação",
        key="pergunta_digitada",
        height=130,
        placeholder="Digite livremente sua pergunta, mesmo com erros de português. Exemplo: Qual procedimento trata de trabalho em altura?",
    )

    if st.button("🔎 Consultar documentos e responder", type="primary", use_container_width=True):
        if not pergunta.strip():
            st.warning("Digite uma pergunta antes de consultar.")
        elif not base:
            st.error("Nenhum documento foi encontrado nas pastas configuradas.")
        else:
            with st.spinner("Buscando documentos relevantes e consultando a IA..."):
                docs_relevantes = buscar_documentos_relevantes(pergunta, base)

                if not docs_relevantes:
                    st.warning("Nenhum documento diretamente relacionado foi localizado. Tente usar outras palavras-chave.")
                else:
                    resposta = responder_com_ia(pergunta, docs_relevantes)

                    st.markdown("## Resposta do Consultor Virtual")
                    st.markdown(resposta)

                    audio_bytes, erro_audio = gerar_audio_ia(resposta)
                    if audio_bytes:
                        st.markdown("## Resposta em áudio")
                        exibir_audio_automatico(audio_bytes)
                    elif erro_audio:
                        st.warning(erro_audio)

                    st.markdown("## Documentos relacionados")
                    for idx, doc in enumerate(docs_relevantes, 1):
                        st.markdown(
                            f"""
                            <div class="doc-card">
                                <div class="doc-title">{idx}. {doc['nome']}</div>
                                <div class="doc-meta">Categoria: {doc['categoria']} | Tipo: {doc['extensao']} | Tamanho: {doc['tamanho_mb']:.2f} MB</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        botao_download_arquivo(doc, f"chat_{idx}")

# ----------------------------
# ABA 2: CATÁLOGO
# ----------------------------
with tab_catalogo:
    st.subheader("Catálogo de documentos disponíveis")

    busca = st.text_input("Pesquisar no catálogo", placeholder="Digite: altura, eletricidade, andaime, EPI, formulário...")
    categoria_filtro = st.selectbox("Filtrar por categoria", ["Todas"] + list(PASTAS_DOCUMENTOS.keys()))

    docs_filtrados = base

    if categoria_filtro != "Todas":
        docs_filtrados = [d for d in docs_filtrados if d["categoria"] == categoria_filtro]

    if busca.strip():
        busca_norm = normalizar_texto(busca)
        docs_filtrados = [
            d for d in docs_filtrados
            if busca_norm in normalizar_texto(d["nome"] + " " + d["categoria"] + " " + d.get("texto", "")[:3000])
        ]

    st.caption(f"{len(docs_filtrados)} documento(s) encontrado(s).")

    for idx, doc in enumerate(docs_filtrados, 1):
        with st.container():
            st.markdown(
                f"""
                <div class="doc-card">
                    <div class="doc-title">{doc['nome']}</div>
                    <div class="doc-meta">Categoria: {doc['categoria']} | Tipo: {doc['extensao']} | Tamanho: {doc['tamanho_mb']:.2f} MB | Páginas lidas: {doc.get('paginas', 0)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            botao_download_arquivo(doc, f"catalogo_{idx}")

# ----------------------------
# ABA 3: CONFIGURAÇÕES
# ----------------------------
with tab_config:
    st.subheader("Configurações do sistema")

    st.markdown("### Caminho principal")
    st.code(str(BASE_DIR), language="text")

    st.markdown("### Pastas configuradas")
    for categoria, pasta in PASTAS_DOCUMENTOS.items():
        st.markdown(f"**{categoria}**")
        st.code(str(pasta), language="text")

    st.markdown("### Status da chave da OpenAI")
    if os.getenv("OPENAI_API_KEY"):
        st.success("OPENAI_API_KEY configurada.")
    else:
        st.error("OPENAI_API_KEY não configurada.")

    st.markdown("### Observação importante")
    st.info(
        "Para a IA responder com base no conteúdo interno dos arquivos, recomenda-se que os documentos estejam em PDF com texto selecionável. "
        "Arquivos DOCX e XLSX entram no catálogo para download, mas a leitura automática completa ainda não foi implementada neste modelo inicial."
    )

# =========================================================
# 9. RODAPÉ
# =========================================================

st.divider()
st.caption(f"{EMPRESA} | Consultor Virtual SGI | Desenvolvido em Streamlit + OpenAI | {datetime.now().year}")
