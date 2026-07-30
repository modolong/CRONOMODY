# -*- coding: utf-8 -*-
"""
CRONOMODY - Plataforma Inteligente de Estudos
===============================================
Aplicativo completo em Streamlit para gestão de estudos com:
- Dashboard com KPIs e mapa de calor de constância
- Cronograma com pesos automáticos e modo ciclo de estudos
- Importador de editais/materiais (PDF/TXT) com geração de flashcards e questões
- Flashcards com repetição espaçada (algoritmo SM-2)
- Simulador de questões com relatório de desempenho
- Cronômetro Pomodoro
- Relatórios semanais e curva de esquecimento de Ebbinghaus

Autor: Engenharia de Software Educacional
Banco de dados: SQLite local (cronomody.db)
"""

import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta
import json
import random
import time
import re
import io

# Extração de PDF (pypdf é o sucessor mantido do PyPDF2)
try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None

# =============================================================================
# CONFIGURAÇÃO GERAL DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="CRONOMODY",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = "cronomody.db"

# =============================================================================
# CAMADA DE BANCO DE DADOS (SQLite)
# =============================================================================

def get_conn():
    """Retorna uma conexão SQLite com row_factory configurado."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Cria todas as tabelas necessárias caso ainda não existam."""
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            exam_date TEXT,
            weekly_hours REAL DEFAULT 20
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER,
            name TEXT NOT NULL,
            importance INTEGER DEFAULT 3,
            difficulty INTEGER DEFAULT 3,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            ease REAL DEFAULT 2.5,
            interval REAL DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            due_date TEXT,
            last_review TEXT,
            created_at TEXT,
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            statement TEXT NOT NULL,
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, option_e TEXT,
            correct_option TEXT,
            explanation TEXT,
            priority REAL DEFAULT 1.0,
            created_at TEXT,
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS question_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            subject_id INTEGER,
            is_correct INTEGER,
            timestamp TEXT,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcard_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flashcard_id INTEGER,
            quality INTEGER,
            timestamp TEXT,
            FOREIGN KEY (flashcard_id) REFERENCES flashcards(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS study_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT,
            subject_id INTEGER,
            minutes REAL,
            activity_type TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def run_query(query, params=(), fetch=False, many=False):
    """Executa uma query genérica com tratamento de erros."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        result = None
        if fetch:
            result = cur.fetchall() if many else cur.fetchone()
        conn.commit()
        return result
    except sqlite3.Error as e:
        st.error(f"Erro no banco de dados: {e}")
        return None
    finally:
        conn.close()


def df_query(query, params=()):
    """Executa uma query e retorna um DataFrame do pandas."""
    conn = get_conn()
    try:
        df = pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"Erro ao consultar dados: {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


init_db()

# Garante que exista ao menos um curso padrão para o Modo Multi Cursos
if df_query("SELECT * FROM courses").empty:
    run_query(
        "INSERT INTO courses (name, exam_date, weekly_hours) VALUES (?, ?, ?)",
        ("Curso Principal", (date.today() + timedelta(days=90)).isoformat(), 20),
    )

# =============================================================================
# ESTADO DE SESSÃO (para o curso ativo, Pomodoro, etc.)
# =============================================================================
if "active_course_id" not in st.session_state:
    first_course = df_query("SELECT id FROM courses ORDER BY id LIMIT 1")
    st.session_state.active_course_id = int(first_course.iloc[0]["id"])

if "pomodoro_running" not in st.session_state:
    st.session_state.pomodoro_running = False
if "pomodoro_start_ts" not in st.session_state:
    st.session_state.pomodoro_start_ts = None
if "pomodoro_mode" not in st.session_state:
    st.session_state.pomodoro_mode = "foco"  # foco | pausa
if "pomodoro_cycle_count" not in st.session_state:
    st.session_state.pomodoro_cycle_count = 0
if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = None
if "show_answer_map" not in st.session_state:
    st.session_state.show_answer_map = {}

# =============================================================================
# FUNÇÕES DE LÓGICA DE NEGÓCIO
# =============================================================================

def calcular_peso(importancia: int, dificuldade: int) -> float:
    """
    Fórmula de peso: dá mais força à importância do que à dificuldade,
    pois matérias importantes devem dominar o cronograma mesmo que fáceis,
    mas a dificuldade também empurra a necessidade de mais horas.
    """
    return round((importancia * 3) + (dificuldade * 2), 2)


def distribuir_horas(subjects_df: pd.DataFrame, total_horas: float) -> pd.DataFrame:
    """Distribui as horas semanais proporcionalmente ao peso de cada matéria."""
    if subjects_df.empty:
        return subjects_df
    soma_pesos = subjects_df["weight"].sum()
    if soma_pesos == 0:
        subjects_df["weekly_hours_alloc"] = 0
    else:
        subjects_df["weekly_hours_alloc"] = (
            (subjects_df["weight"] / soma_pesos) * total_horas
        ).round(2)
    return subjects_df


def calcular_desempenho_materia(subject_id: int) -> float:
    """Retorna a taxa de acerto (0 a 1) de uma matéria com base no histórico."""
    df = df_query(
        "SELECT is_correct FROM question_attempts WHERE subject_id = ?", (subject_id,)
    )
    if df.empty:
        return 0.5  # neutro, sem histórico
    return df["is_correct"].mean()


def sugerir_ordem_ciclo(subjects_df: pd.DataFrame) -> pd.DataFrame:
    """
    Modo Ciclo de Estudos: ordena as matérias por prioridade dinâmica,
    combinando peso (importância x dificuldade) com desempenho acumulado.
    Prioridade = peso * (1 - taxa_de_acerto) -> quanto pior o desempenho
    e maior o peso, mais cedo a matéria entra no ciclo.
    """
    if subjects_df.empty:
        return subjects_df
    subjects_df = subjects_df.copy()
    subjects_df["desempenho"] = subjects_df["id"].apply(calcular_desempenho_materia)
    subjects_df["prioridade_ciclo"] = (
        subjects_df["weight"] * (1 - subjects_df["desempenho"] + 0.1)
    ).round(2)
    return subjects_df.sort_values("prioridade_ciclo", ascending=False)


def fator_urgencia_prova(exam_date_str: str) -> float:
    """
    Calcula um fator multiplicador de urgência que aumenta conforme a
    data da prova se aproxima. Usado para comprimir intervalos de revisão.
    >1 dias afastados -> fator ~1.0 (normal)
    <=7 dias -> fator até 2.5 (revisões muito mais frequentes)
    """
    if not exam_date_str:
        return 1.0
    try:
        exam_date = datetime.fromisoformat(exam_date_str).date()
    except ValueError:
        return 1.0
    dias_restantes = (exam_date - date.today()).days
    if dias_restantes <= 0:
        return 3.0
    elif dias_restantes <= 7:
        return 2.5
    elif dias_restantes <= 14:
        return 1.8
    elif dias_restantes <= 30:
        return 1.3
    return 1.0


# ---- Algoritmo SM-2 (repetição espaçada, estilo Anki) ----------------------
def sm2(quality: int, repetitions: int, ease: float, interval: float, urgencia: float = 1.0):
    """
    Implementação do algoritmo SM-2 (SuperMemo 2).
    quality: 0 (errado/difícil), 3 (bom/médio) ou 5 (fácil) - mapeado de botões Anki-like
    Retorna: (novas_repeticoes, novo_ease, novo_intervalo, nova_data_vencimento)
    """
    if quality < 3:
        # Errou ou achou difícil -> reinicia repetições, intervalo curto
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease, 1)
        repetitions += 1

    # Atualiza o fator de facilidade (ease factor), nunca abaixo de 1.3
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(1.3, round(ease, 2))

    # Aplica o fator de urgência da prova (comprime intervalos se a prova está perto)
    interval_ajustado = max(1, round(interval / urgencia))
    due_date = (date.today() + timedelta(days=interval_ajustado)).isoformat()

    return repetitions, ease, interval, due_date


def registrar_estudo(subject_id, minutos, tipo):
    """Registra uma sessão de estudo no log (usado pelo mapa de calor)."""
    run_query(
        "INSERT INTO study_log (log_date, subject_id, minutes, activity_type) VALUES (?, ?, ?, ?)",
        (date.today().isoformat(), subject_id, minutos, tipo),
    )


# ---- Filtros de limpeza para materiais médicos (remoção de ruído) ---------
# Padrões típicos de cabeçalho/rodapé/marca d'água/avisos legais em apostilas e livros
PADROES_RUIDO = [
    r"^p[aá]gina\s*\d+", r"^\d+\s*/\s*\d+$", r"^\d{1,4}$",
    r"^www\.", r"https?://", r"^\S+@\S+\.\S+$",  # sites e e-mails isolados
    r"^©", r"todos os direitos reservados", r"^isbn", r"^copyright",
    r"confidencial", r"amostra gr[aá]tis", r"^vers[aã]o\s+demonstrativa$",
    r"n[aã]o\s+comercializ", r"reproduç[aã]o proibida", r"material\s+did[aá]tico",
    r"^cap[ií]tulo\s*\d+$", r"^sum[aá]rio$", r"^[\-_=]{3,}$", r"^anexo\s*[iv\d]+$",
    r"^edi[cç][aã]o\s*:?", r"impresso no brasil", r"todos os direitos autorais",
]
PADROES_RUIDO_RE = re.compile("|".join(PADROES_RUIDO), re.IGNORECASE)

# Vocabulário-âncora para validar relevância clínica/médica de uma frase.
# Frases sem nenhum destes indícios são tratadas como ruído/contexto não essencial.
TERMOS_MEDICOS = [
    "diagnóstic", "tratamento", "sintoma", "síndrome", "doença", "paciente",
    "clínic", "fisiopatolog", "farmac", "anatôm", "anatomia", "patolog",
    "terapêutic", "cirurg", "exame", "prognós", "etiolog", "epidemiolog",
    "hospital", "medicament", "dose", "posologia", "infec", "inflama",
    "tumor", "câncer", "neoplas", "cardíac", "cardiovascular", "pulmonar",
    "respirat", "renal", "hepátic", "neurológ", "neuronal", "endócrin",
    "hormôn", "vacina", "vírus", "bactéria", "antibiótic", "lesão",
    "biópsia", "histológic", "célula", "tecido", "órgão", "sangue",
    "sistema imun", "músculo", "esquelétic", "reflexo", "artéria", "veia",
    "gestaç", "pediátri", "geriátri", "psiquiátri", "ortopéd", "dermatológ",
    "oncológ", "metaból", "fisiológ", "anestes", "vacinaç", "imunológ",
]
SUFIXOS_MEDICOS = (
    "ite", "ose", "emia", "patia", "ectomia", "oma", "algia", "grafia",
    "terapia", "plastia", "scopia", "trofia", "gênese",
)


def eh_ruido(linha: str) -> bool:
    """Detecta se uma linha é cabeçalho, rodapé, numeração de página ou marca d'água."""
    l = linha.strip()
    if not l or len(l) <= 3:
        return True
    if PADROES_RUIDO_RE.search(l):
        return True
    # Linhas curtas totalmente em maiúsculas tendem a ser cabeçalhos/títulos repetidos de página
    if l.isupper() and len(l.split()) <= 3:
        return True
    return False


def eh_conteudo_medico(frase: str) -> bool:
    """
    Heurística que valida se uma frase é essencialmente conteúdo médico
    (e não ruído editorial, institucional ou administrativo do material).
    """
    f = frase.lower()
    if any(termo in f for termo in TERMOS_MEDICOS):
        return True
    for p in f.split():
        p_limpo = p.strip(".,;:()")
        if len(p_limpo) > 7 and p_limpo.endswith(SUFIXOS_MEDICOS):
            return True
    return False


def remover_cabecalhos_rodapes_repetidos(paginas: list) -> list:
    """
    Detecta linhas que se repetem de forma idêntica em várias páginas do PDF
    (típico de cabeçalhos, rodapés e marcas d'água institucionais) e as remove
    de todas as ocorrências, preservando apenas o conteúdo único de cada página.
    """
    if len(paginas) < 2:
        return paginas
    contagem = {}
    for pagina in paginas:
        linhas_unicas = {l.strip() for l in pagina.split("\n") if l.strip()}
        for l in linhas_unicas:
            contagem[l] = contagem.get(l, 0) + 1
    # Considera "repetida" (logo, ruído) uma linha presente em ao menos 1/3 das páginas
    limite_repeticao = max(2, len(paginas) // 3)
    linhas_repetidas = {l for l, c in contagem.items() if c >= limite_repeticao and len(l) < 120}
    novas_paginas = []
    for pagina in paginas:
        linhas_filtradas = [l for l in pagina.split("\n") if l.strip() not in linhas_repetidas]
        novas_paginas.append("\n".join(linhas_filtradas))
    return novas_paginas


def limpar_texto_medico(texto: str) -> str:
    """
    Pipeline de limpeza de conteúdo: remove ruído linha a linha (rodapés,
    numeração de página, marcas d'água, avisos legais/editoriais), preservando
    apenas texto que representa efetivamente o conteúdo do material médico.
    """
    linhas = texto.split("\n")
    linhas_limpas = [l for l in linhas if not eh_ruido(l)]
    return "\n".join(linhas_limpas)


# ---- Extração e geração de conteúdo a partir de PDF/TXT --------------------
def extrair_texto_arquivo(uploaded_file):
    """
    Extrai texto de um arquivo PDF ou TXT enviado pelo usuário, já aplicando
    a limpeza de cabeçalhos/rodapés/marcas d'água. Retorna uma tupla
    (texto_limpo, estatisticas) onde estatisticas informa quantas linhas
    de ruído foram descartadas, para transparência com o usuário.
    """
    texto_bruto = ""
    try:
        if uploaded_file.type == "application/pdf" or uploaded_file.name.lower().endswith(".pdf"):
            if PdfReader is None:
                st.error("Biblioteca de leitura de PDF não encontrada. Instale 'pypdf'.")
                return "", {}
            reader = PdfReader(uploaded_file)
            paginas = [(page.extract_text() or "") for page in reader.pages]
            # 1ª etapa: remove cabeçalhos/rodapés/marcas d'água repetidos entre páginas
            paginas_sem_repeticao = remover_cabecalhos_rodapes_repetidos(paginas)
            texto_bruto = "\n".join(paginas_sem_repeticao)
        else:
            texto_bruto = uploaded_file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        st.error(f"Erro ao ler o arquivo: {e}")
        return "", {}

    linhas_antes = len([l for l in texto_bruto.split("\n") if l.strip()])
    # 2ª etapa: remove ruído linha a linha (numeração, avisos legais, etc.)
    texto_limpo = limpar_texto_medico(texto_bruto)
    linhas_depois = len([l for l in texto_limpo.split("\n") if l.strip()])

    estatisticas = {
        "linhas_removidas": linhas_antes - linhas_depois,
        "linhas_antes": linhas_antes,
        "linhas_depois": linhas_depois,
    }
    return texto_limpo, estatisticas


def extrair_topicos(texto: str, max_topicos: int = 25):
    """
    Heurística leve de extração de tópicos: identifica linhas curtas,
    numeradas ou em caixa alta que costumam representar títulos de
    seções em apostilas/editais, já ignorando linhas de ruído
    (cabeçalhos, rodapés, numeração de página e marcas d'água).
    """
    linhas = [l.strip() for l in texto.split("\n") if l.strip() and not eh_ruido(l)]
    topicos = []
    padrao_numerado = re.compile(r"^(\d+[\.\)]|\u2022|-)\s*.+")
    for linha in linhas:
        palavras = linha.split()
        if not (2 <= len(palavras) <= 12):
            continue
        eh_maiuscula = linha.upper() == linha and len(linha) > 4
        eh_numerada = bool(padrao_numerado.match(linha))
        eh_titulo_capitalizado = linha.istitle()
        if eh_maiuscula or eh_numerada or eh_titulo_capitalizado:
            limpo = re.sub(r"^(\d+[\.\)]|\u2022|-)\s*", "", linha).strip()
            if limpo and limpo not in topicos:
                topicos.append(limpo)
        if len(topicos) >= max_topicos:
            break
    if not topicos:
        # Fallback: usa as primeiras frases relevantes como pseudo-tópicos
        frases = re.split(r"(?<=[\.\!\?])\s+", texto)
        topicos = [f.strip()[:80] for f in frases if len(f.strip()) > 20][:max_topicos]
    return topicos


def gerar_flashcards_de_texto(texto: str, subject_id: int, limite: int = 15):
    """
    Gera flashcards automaticamente a partir do texto extraído.
    Estratégia: quebra o texto em frases, descarta ruído (cabeçalho/rodapé/
    marca d'água já foram removidos na extração) e mantém apenas frases com
    conteúdo clínico reconhecível, criando pares pergunta/resposta a partir
    delas. Retorna (quantidade_criada, quantidade_descartada_por_nao_medica).
    """
    candidatas = [f.strip() for f in re.split(r"(?<=[\.\!\?])\s+", texto) if len(f.strip()) > 30]
    frases_medicas = [f for f in candidatas if not eh_ruido(f) and eh_conteudo_medico(f)]
    descartadas = len(candidatas) - len(frases_medicas)

    criados = 0
    for frase in frases_medicas:
        if criados >= limite:
            break
        palavras = frase.split()
        if len(palavras) < 6:
            continue
        frente = f"Explique / defina: {' '.join(palavras[:8])}..."
        verso = frase
        run_query(
            """INSERT INTO flashcards
               (subject_id, front, back, ease, interval, repetitions, due_date, last_review, created_at, source)
               VALUES (?, ?, ?, 2.5, 0, 0, ?, NULL, ?, 'importado')""",
            (subject_id, frente, verso, date.today().isoformat(), datetime.now().isoformat()),
        )
        criados += 1
    return criados, descartadas


def gerar_questoes_de_texto(texto: str, subject_id: int, limite: int = 10):
    """
    Gera questões de múltipla escolha (cloze) a partir do texto,
    ocultando uma palavra-chave da frase e criando distratores simples.
    Apenas frases com conteúdo clínico reconhecível (após descarte de
    ruído de cabeçalho/rodapé/marca d'água) entram como base das questões.
    Retorna (quantidade_criada, quantidade_descartada_por_nao_medica).
    """
    candidatas = [f.strip() for f in re.split(r"(?<=[\.\!\?])\s+", texto) if len(f.strip()) > 40]
    frases = [f for f in candidatas if not eh_ruido(f) and eh_conteudo_medico(f)]
    descartadas = len(candidatas) - len(frases)

    criados = 0
    # Banco de palavras-chave usado para gerar distratores plausíveis,
    # extraído apenas das frases já filtradas como conteúdo médico
    banco_palavras = list({p.strip(".,;:()") for f in frases for p in f.split() if len(p) > 5})

    for frase in frases:
        if criados >= limite:
            break
        palavras = [p for p in frase.split() if len(p.strip(".,;:()")) > 5]
        if not palavras:
            continue
        alvo = random.choice(palavras)
        alvo_limpo = alvo.strip(".,;:()")
        enunciado = frase.replace(alvo, "____________", 1)

        distratores = random.sample(
            [p for p in banco_palavras if p.lower() != alvo_limpo.lower()],
            k=min(4, max(0, len(banco_palavras) - 1)),
        )
        opcoes = distratores[:4] + [alvo_limpo]
        random.shuffle(opcoes)
        while len(opcoes) < 5:
            opcoes.append("Nenhuma das anteriores")
        letras = ["A", "B", "C", "D", "E"]
        correta = letras[opcoes.index(alvo_limpo)] if alvo_limpo in opcoes else "E"

        run_query(
            """INSERT INTO questions
               (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                correct_option, explanation, priority, created_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'importado')""",
            (
                subject_id, enunciado,
                opcoes[0], opcoes[1], opcoes[2], opcoes[3], opcoes[4],
                correta, f"Trecho original: {frase}",
                datetime.now().isoformat(),
            ),
        )
        criados += 1
    return criados, descartadas


# =============================================================================
# COMPONENTES VISUAIS REUTILIZÁVEIS
# =============================================================================

def render_kpi_cards(total_questoes, total_flashcards, pct_acerto):
    col1, col2, col3 = st.columns(3)
    col1.metric("📝 Total de Questões Feitas", f"{total_questoes}")
    col2.metric("🎴 Flashcards Criados/Estudados", f"{total_flashcards}")
    col3.metric("🎯 Percentual Geral de Acertos", f"{pct_acerto:.1f}%")


def render_heatmap_constancia():
    """Mapa de calor de constância de estudos (estilo GitHub) para o ano corrente."""
    df = df_query(
        "SELECT log_date, SUM(minutes) as minutos FROM study_log GROUP BY log_date"
    )
    ano = date.today().year
    inicio = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    todos_dias = pd.date_range(inicio, fim, freq="D")

    minutos_por_dia = {}
    if not df.empty:
        df["log_date"] = pd.to_datetime(df["log_date"])
        minutos_por_dia = dict(zip(df["log_date"], df["minutos"]))

    valores, semanas, dias_semana, textos = [], [], [], []
    for d in todos_dias:
        valores.append(minutos_por_dia.get(d, 0))
        semanas.append(int(d.strftime("%U")))
        dias_semana.append(d.weekday())
        textos.append(f"{d.date()} - {minutos_por_dia.get(d, 0):.0f} min")

    matriz = np.full((7, max(semanas) + 1), np.nan)
    texto_matriz = np.full((7, max(semanas) + 1), "", dtype=object)
    for v, s, dw, t in zip(valores, semanas, dias_semana, textos):
        matriz[dw, s] = v
        texto_matriz[dw, s] = t

    fig = go.Figure(
        data=go.Heatmap(
            z=matriz,
            text=texto_matriz,
            hoverinfo="text",
            colorscale="Greens",
            showscale=False,
            xgap=2, ygap=2,
        )
    )
    fig.update_layout(
        title=f"Constância de Estudos - {ano}",
        yaxis=dict(
            tickmode="array", tickvals=list(range(7)),
            ticktext=["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"], autorange="reversed",
        ),
        xaxis=dict(title="Semana do ano"),
        height=260, margin=dict(t=40, b=20, l=40, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# SIDEBAR - NAVEGAÇÃO E SELEÇÃO DE CURSO (MULTI CURSOS)
# =============================================================================
st.sidebar.title("⏱️ CRONOMODY")
st.sidebar.caption("Sua plataforma de alta performance nos estudos")

cursos_df = df_query("SELECT * FROM courses")
nomes_cursos = cursos_df["name"].tolist()
ids_cursos = cursos_df["id"].tolist()

with st.sidebar.expander("📚 Modo Multi Cursos", expanded=False):
    curso_escolhido = st.selectbox(
        "Curso / Frente de estudo ativa",
        options=ids_cursos,
        format_func=lambda cid: cursos_df.loc[cursos_df["id"] == cid, "name"].values[0],
        index=ids_cursos.index(st.session_state.active_course_id)
        if st.session_state.active_course_id in ids_cursos else 0,
    )
    st.session_state.active_course_id = curso_escolhido

    novo_curso_nome = st.text_input("Novo curso/concurso", key="novo_curso_nome")
    if st.button("➕ Adicionar curso"):
        if novo_curso_nome.strip():
            try:
                run_query(
                    "INSERT INTO courses (name, exam_date, weekly_hours) VALUES (?, ?, ?)",
                    (novo_curso_nome.strip(), (date.today() + timedelta(days=90)).isoformat(), 20),
                )
                st.success(f"Curso '{novo_curso_nome}' criado!")
                st.rerun()
            except sqlite3.IntegrityError:
                st.warning("Já existe um curso com esse nome.")
        else:
            st.warning("Digite um nome válido para o curso.")

curso_atual = cursos_df[cursos_df["id"] == st.session_state.active_course_id].iloc[0]

pagina = st.sidebar.radio(
    "Navegação",
    [
        "🏠 Dashboard",
        "📅 Cronograma, Pesos e Ciclo",
        "📥 Importador de Editais/Materiais",
        "🎴 Flashcards (SM-2)",
        "❓ Simulador de Questões",
        "🍅 Pomodoro",
        "📊 Relatórios e Ebbinghaus",
    ],
)

st.sidebar.divider()
st.sidebar.caption(f"Curso ativo: **{curso_atual['name']}**")
if curso_atual["exam_date"]:
    dias_restantes = (datetime.fromisoformat(curso_atual["exam_date"]).date() - date.today()).days
    st.sidebar.caption(f"📆 Faltam **{dias_restantes} dias** para a prova.")

# =============================================================================
# PÁGINA 1 - DASHBOARD
# =============================================================================
if pagina == "🏠 Dashboard":
    st.title("🏠 Dashboard Geral")
    st.caption("Visão consolidada da sua performance de estudos.")

    total_questoes = df_query("SELECT COUNT(*) as c FROM question_attempts").iloc[0]["c"]
    total_flashcards = df_query("SELECT COUNT(*) as c FROM flashcards").iloc[0]["c"]
    acertos_df = df_query("SELECT AVG(is_correct) as media FROM question_attempts")
    pct_acerto = (acertos_df.iloc[0]["media"] or 0) * 100

    render_kpi_cards(total_questoes, total_flashcards, pct_acerto)

    st.divider()
    render_heatmap_constancia()

    st.divider()
    st.subheader("📈 Desempenho por Matéria (curso ativo)")
    subjects_df = df_query(
        "SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),)
    )
    if subjects_df.empty:
        st.info("Cadastre matérias na aba 'Cronograma, Pesos e Ciclo' para ver o desempenho aqui.")
    else:
        desempenhos = []
        for _, row in subjects_df.iterrows():
            desempenhos.append({
                "Matéria": row["name"],
                "Acerto (%)": round(calcular_desempenho_materia(row["id"]) * 100, 1),
            })
        fig = px.bar(pd.DataFrame(desempenhos), x="Matéria", y="Acerto (%)", color="Acerto (%)",
                     color_continuous_scale="RdYlGn", range_color=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# PÁGINA 2 - CRONOGRAMA, PESOS E CICLO DE ESTUDOS
# =============================================================================
elif pagina == "📅 Cronograma, Pesos e Ciclo":
    st.title("📅 Cronograma, Pesos e Ciclo de Estudos")

    with st.expander("⚙️ Configurações do curso", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            nova_data_prova = st.date_input(
                "Data da prova",
                value=datetime.fromisoformat(curso_atual["exam_date"]).date()
                if curso_atual["exam_date"] else date.today() + timedelta(days=90),
            )
        with c2:
            novas_horas = st.number_input(
                "Total de horas semanais disponíveis", min_value=1.0, max_value=100.0,
                value=float(curso_atual["weekly_hours"]), step=1.0,
            )
        if st.button("💾 Salvar configurações do curso"):
            run_query(
                "UPDATE courses SET exam_date = ?, weekly_hours = ? WHERE id = ?",
                (nova_data_prova.isoformat(), novas_horas, int(curso_atual["id"])),
            )
            st.success("Configurações atualizadas!")
            st.rerun()

    st.subheader("➕ Cadastrar nova matéria")
    with st.form("form_nova_materia", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        nome_materia = col1.text_input("Nome da matéria")
        importancia = col2.slider("Importância", 1, 5, 3)
        dificuldade = col3.slider("Dificuldade", 1, 5, 3)
        enviado = st.form_submit_button("Adicionar matéria")
        if enviado:
            if nome_materia.strip():
                run_query(
                    "INSERT INTO subjects (course_id, name, importance, difficulty) VALUES (?, ?, ?, ?)",
                    (int(curso_atual["id"]), nome_materia.strip(), importancia, dificuldade),
                )
                st.success(f"Matéria '{nome_materia}' cadastrada!")
                st.rerun()
            else:
                st.warning("Informe um nome para a matéria.")

    st.divider()
    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))

    if subjects_df.empty:
        st.info("Nenhuma matéria cadastrada ainda para este curso.")
    else:
        subjects_df["weight"] = subjects_df.apply(
            lambda r: calcular_peso(r["importance"], r["difficulty"]), axis=1
        )
        subjects_df = distribuir_horas(subjects_df, float(curso_atual["weekly_hours"]))

        st.subheader("📋 Tabela de matérias, pesos e horas semanais")
        tabela_exibicao = subjects_df[
            ["name", "importance", "difficulty", "weight", "weekly_hours_alloc"]
        ].rename(columns={
            "name": "Matéria", "importance": "Importância", "difficulty": "Dificuldade",
            "weight": "Peso", "weekly_hours_alloc": "Horas/semana alocadas",
        })
        st.dataframe(tabela_exibicao, use_container_width=True, hide_index=True)

        with st.expander("🗑️ Remover matéria"):
            materia_remover = st.selectbox(
                "Selecione a matéria", subjects_df["name"].tolist(), key="remover_materia"
            )
            if st.button("Remover matéria selecionada"):
                sid = int(subjects_df.loc[subjects_df["name"] == materia_remover, "id"].values[0])
                run_query("DELETE FROM subjects WHERE id = ?", (sid,))
                st.success("Matéria removida.")
                st.rerun()

        st.divider()
        st.subheader("🔄 Modo de organização do cronograma")
        modo = st.radio(
            "Escolha o modo de cronograma",
            ["Cronograma Semanal Fixo", "Modo Ciclo de Estudos"],
            horizontal=True,
        )

        urgencia = fator_urgencia_prova(curso_atual["exam_date"])
        if urgencia > 1.0:
            st.warning(
                f"⚠️ A prova está se aproximando! Fator de intensificação de revisões: **{urgencia}x**. "
                "O algoritmo está comprimindo os intervalos de revisão automaticamente."
            )

        if modo == "Cronograma Semanal Fixo":
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            distribuicao = []
            for i, row in subjects_df.iterrows():
                dia_sugerido = dias[i % len(dias)]
                distribuicao.append({
                    "Dia sugerido": dia_sugerido,
                    "Matéria": row["name"],
                    "Horas na semana": row["weekly_hours_alloc"],
                })
            st.dataframe(pd.DataFrame(distribuicao), use_container_width=True, hide_index=True)
        else:
            ciclo_df = sugerir_ordem_ciclo(subjects_df)
            st.markdown("**Ordem sugerida do ciclo (prioridade dinâmica = peso × desempenho fraco):**")
            ciclo_exibicao = ciclo_df[["name", "weight", "desempenho", "prioridade_ciclo"]].rename(
                columns={
                    "name": "Matéria", "weight": "Peso",
                    "desempenho": "Taxa de Acerto Atual", "prioridade_ciclo": "Prioridade no Ciclo",
                }
            )
            ciclo_exibicao["Taxa de Acerto Atual"] = (ciclo_exibicao["Taxa de Acerto Atual"] * 100).round(1)
            st.dataframe(ciclo_exibicao, use_container_width=True, hide_index=True)
            st.info(
                f"👉 Próxima matéria recomendada pelo ciclo: **{ciclo_df.iloc[0]['name']}**"
            )

# =============================================================================
# PÁGINA 3 - IMPORTADOR DE EDITAIS E MATERIAIS
# =============================================================================
elif pagina == "📥 Importador de Editais/Materiais":
    st.title("📥 Importador de Editais e Materiais de Estudo")
    st.caption(
        "Envie um PDF ou TXT. O sistema descarta automaticamente cabeçalhos, rodapés, "
        "numeração de página, marcas d'água e avisos editoriais, extrai os tópicos e gera "
        "flashcards e questões baseados estritamente no conteúdo médico essencial do material."
    )

    arquivo = st.file_uploader("Selecione o arquivo (PDF ou TXT)", type=["pdf", "txt"])

    if arquivo is not None:
        with st.spinner("Lendo, limpando e processando o material..."):
            texto_extraido, stats_limpeza = extrair_texto_arquivo(arquivo)

        if not texto_extraido.strip():
            st.error("Não foi possível extrair texto do arquivo enviado.")
        else:
            st.success(f"Arquivo processado! {len(texto_extraido)} caracteres úteis extraídos.")

            if stats_limpeza.get("linhas_removidas", 0) > 0:
                st.info(
                    f"🧹 Limpeza automática: **{stats_limpeza['linhas_removidas']} linha(s)** de "
                    f"cabeçalho/rodapé/numeração/marca d'água/aviso editorial foram descartadas "
                    f"(de {stats_limpeza['linhas_antes']} linhas originais), mantendo "
                    f"{stats_limpeza['linhas_depois']} linhas de conteúdo."
                )

            topicos = extrair_topicos(texto_extraido)

            st.subheader("🗂️ Tópicos identificados no material")
            st.write(topicos if topicos else "Nenhum tópico claro identificado.")

            with st.expander("👁️ Visualizar texto já limpo (prévia)"):
                st.text_area("Prévia do conteúdo pós-limpeza", texto_extraido[:3000], height=200)

            st.divider()
            st.subheader("⚙️ Associar conteúdo a uma matéria")

            subjects_df = df_query(
                "SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),)
            )
            opcoes_materia = ["➕ Criar nova matéria a partir deste material"] + subjects_df["name"].tolist()
            escolha = st.selectbox("Matéria de destino", opcoes_materia)

            if escolha.startswith("➕"):
                nome_sugerido = topicos[0] if topicos else arquivo.name.rsplit(".", 1)[0]
                nome_nova_materia = st.text_input("Nome da nova matéria", value=nome_sugerido)
            else:
                nome_nova_materia = None

            col1, col2 = st.columns(2)
            qtd_flashcards = col1.slider("Quantidade de flashcards a gerar", 5, 40, 15)
            qtd_questoes = col2.slider("Quantidade de questões a gerar", 5, 30, 10)

            if st.button("🤖 Gerar flashcards e questões automaticamente"):
                if escolha.startswith("➕"):
                    if not nome_nova_materia.strip():
                        st.warning("Informe um nome para a nova matéria.")
                        st.stop()
                    run_query(
                        "INSERT INTO subjects (course_id, name, importance, difficulty) VALUES (?, ?, 3, 3)",
                        (int(curso_atual["id"]), nome_nova_materia.strip()),
                    )
                    subject_id = df_query(
                        "SELECT id FROM subjects WHERE name = ? AND course_id = ?",
                        (nome_nova_materia.strip(), int(curso_atual["id"])),
                    ).iloc[0]["id"]
                else:
                    subject_id = int(subjects_df.loc[subjects_df["name"] == escolha, "id"].values[0])

                with st.spinner("Filtrando conteúdo médico e gerando material de estudo..."):
                    n_fc, desc_fc = gerar_flashcards_de_texto(texto_extraido, int(subject_id), qtd_flashcards)
                    n_q, desc_q = gerar_questoes_de_texto(texto_extraido, int(subject_id), qtd_questoes)

                st.success(
                    f"✅ Gerados {n_fc} flashcards e {n_q} questões, baseados estritamente "
                    f"no conteúdo médico essencial identificado no material."
                )
                total_descartado = desc_fc + desc_q
                if total_descartado > 0:
                    st.caption(
                        f"🩺 {total_descartado} trecho(s) foram ignorados na geração por não "
                        "representarem conteúdo clínico/médico reconhecível (ex: texto institucional, "
                        "administrativo ou contextual não essencial)."
                    )
                if n_fc == 0 and n_q == 0:
                    st.warning(
                        "Nenhum trecho com vocabulário médico reconhecível foi encontrado neste "
                        "material. Verifique se o arquivo enviado é, de fato, conteúdo clínico/médico."
                    )
                st.balloons()

# =============================================================================
# PÁGINA 4 - FLASHCARDS COM SM-2
# =============================================================================
elif pagina == "🎴 Flashcards (SM-2)":
    st.title("🎴 Sistema de Flashcards (Repetição Espaçada SM-2)")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
    if subjects_df.empty:
        st.info("Cadastre uma matéria primeiro (aba Cronograma) ou importe um material.")
        st.stop()

    materia_nome = st.selectbox("Filtrar por matéria", ["Todas"] + subjects_df["name"].tolist())

    with st.expander("➕ Criar flashcard manualmente"):
        with st.form("form_flashcard_manual", clear_on_submit=True):
            materia_fc = st.selectbox("Matéria", subjects_df["name"].tolist(), key="materia_fc_manual")
            frente = st.text_area("Frente (pergunta)")
            verso = st.text_area("Verso (resposta)")
            criar_fc = st.form_submit_button("Criar flashcard")
            if criar_fc:
                if frente.strip() and verso.strip():
                    sid = int(subjects_df.loc[subjects_df["name"] == materia_fc, "id"].values[0])
                    run_query(
                        """INSERT INTO flashcards
                           (subject_id, front, back, ease, interval, repetitions, due_date, created_at, source)
                           VALUES (?, ?, ?, 2.5, 0, 0, ?, ?, 'manual')""",
                        (sid, frente.strip(), verso.strip(), date.today().isoformat(), datetime.now().isoformat()),
                    )
                    st.success("Flashcard criado!")
                    st.rerun()
                else:
                    st.warning("Preencha frente e verso.")

    st.divider()

    query = """
        SELECT f.*, s.name as subject_name FROM flashcards f
        JOIN subjects s ON f.subject_id = s.id
        WHERE s.course_id = ? AND (f.due_date IS NULL OR f.due_date <= ?)
    """
    params = [int(curso_atual["id"]), date.today().isoformat()]
    if materia_nome != "Todas":
        query += " AND s.name = ?"
        params.append(materia_nome)
    query += " ORDER BY f.due_date ASC LIMIT 1"

    cartao = df_query(query, tuple(params))

    total_pendentes = df_query(
        """SELECT COUNT(*) as c FROM flashcards f JOIN subjects s ON f.subject_id = s.id
           WHERE s.course_id = ? AND (f.due_date IS NULL OR f.due_date <= ?)""",
        (int(curso_atual["id"]), date.today().isoformat()),
    ).iloc[0]["c"]

    st.metric("Flashcards pendentes de revisão hoje", total_pendentes)

    if cartao.empty:
        st.success("🎉 Nenhum flashcard pendente no momento. Volte mais tarde ou crie novos!")
    else:
        card = cartao.iloc[0]
        st.subheader(f"📘 Matéria: {card['subject_name']}")
        st.markdown(f"### {card['front']}")

        card_id = int(card["id"])
        mostrar = st.session_state.show_answer_map.get(card_id, False)

        if not mostrar:
            if st.button("👁️ Mostrar Resposta", key=f"show_{card_id}"):
                st.session_state.show_answer_map[card_id] = True
                st.rerun()
        else:
            st.info(card["back"])
            urgencia = fator_urgencia_prova(curso_atual["exam_date"])

            colb1, colb2, colb3 = st.columns(3)

            def avaliar(qualidade):
                reps, ease, interval, due = sm2(
                    qualidade, int(card["repetitions"]), float(card["ease"]),
                    float(card["interval"]), urgencia,
                )
                run_query(
                    """UPDATE flashcards SET repetitions = ?, ease = ?, interval = ?,
                       due_date = ?, last_review = ? WHERE id = ?""",
                    (reps, ease, interval, due, datetime.now().isoformat(), card_id),
                )
                run_query(
                    "INSERT INTO flashcard_reviews (flashcard_id, quality, timestamp) VALUES (?, ?, ?)",
                    (card_id, qualidade, datetime.now().isoformat()),
                )
                registrar_estudo(int(card["subject_id"]), 2, "flashcard")
                st.session_state.show_answer_map[card_id] = False
                st.rerun()

            if colb1.button("❌ Errado/Difícil"):
                avaliar(0)
            if colb2.button("✅ Bom/Médio"):
                avaliar(3)
            if colb3.button("⭐ Fácil"):
                avaliar(5)

# =============================================================================
# PÁGINA 5 - SIMULADOR DE QUESTÕES E DESEMPENHO
# =============================================================================
elif pagina == "❓ Simulador de Questões":
    st.title("❓ Simulador de Questões e Desempenho")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
    if subjects_df.empty:
        st.info("Cadastre uma matéria primeiro ou importe um material com questões.")
        st.stop()

    materia_escolhida = st.selectbox("Escolha a matéria para o simulado", subjects_df["name"].tolist())
    sid = int(subjects_df.loc[subjects_df["name"] == materia_escolhida, "id"].values[0])

    qtd_questoes_disp = df_query("SELECT COUNT(*) as c FROM questions WHERE subject_id = ?", (sid,)).iloc[0]["c"]

    if qtd_questoes_disp == 0:
        st.warning("Nenhuma questão cadastrada para esta matéria. Importe um material ou cadastre manualmente.")

    with st.expander("➕ Cadastrar questão manualmente"):
        with st.form("form_questao_manual", clear_on_submit=True):
            enunciado = st.text_area("Enunciado")
            oa = st.text_input("Opção A")
            ob = st.text_input("Opção B")
            oc = st.text_input("Opção C")
            od = st.text_input("Opção D")
            oe = st.text_input("Opção E")
            correta = st.selectbox("Alternativa correta", ["A", "B", "C", "D", "E"])
            explicacao = st.text_area("Gabarito comentado (explicação)")
            criar_q = st.form_submit_button("Cadastrar questão")
            if criar_q:
                if enunciado.strip() and oa.strip() and ob.strip():
                    run_query(
                        """INSERT INTO questions
                           (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                            correct_option, explanation, priority, created_at, source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'manual')""",
                        (sid, enunciado, oa, ob, oc, od, oe, correta, explicacao, datetime.now().isoformat()),
                    )
                    st.success("Questão cadastrada!")
                    st.rerun()
                else:
                    st.warning("Preencha ao menos enunciado, opção A e opção B.")

    st.divider()

    n_questoes_simulado = st.slider("Quantas questões deseja no simulado?", 1, max(1, int(qtd_questoes_disp)), min(5, max(1, int(qtd_questoes_disp))))

    if st.button("🚀 Iniciar novo simulado"):
        # Prioriza questões com maior 'priority' (as que o usuário mais errou)
        banco = df_query(
            "SELECT * FROM questions WHERE subject_id = ? ORDER BY priority DESC", (sid,)
        )
        if not banco.empty:
            amostra = banco.sample(n=min(n_questoes_simulado, len(banco)), weights=banco["priority"])
            st.session_state.current_quiz = {
                "questions": amostra.to_dict("records"),
                "answers": {},
                "index": 0,
                "subject_id": sid,
                "finished": False,
            }
            st.rerun()

    quiz = st.session_state.current_quiz
    if quiz and not quiz.get("finished") and quiz.get("subject_id") == sid:
        idx = quiz["index"]
        questoes = quiz["questions"]

        if idx < len(questoes):
            q = questoes[idx]
            st.subheader(f"Questão {idx + 1} de {len(questoes)}")
            st.markdown(f"**{q['statement']}**")

            opcoes = {
                "A": q["option_a"], "B": q["option_b"], "C": q["option_c"],
                "D": q["option_d"], "E": q["option_e"],
            }
            opcoes_validas = {k: v for k, v in opcoes.items() if v and str(v).strip()}

            resposta = st.radio(
                "Selecione a alternativa:",
                list(opcoes_validas.keys()),
                format_func=lambda k: f"{k}) {opcoes_validas[k]}",
                key=f"resp_{idx}",
            )

            if st.button("Confirmar resposta", key=f"confirmar_{idx}"):
                correta = str(q["correct_option"]).strip().upper()
                acertou = resposta.strip().upper() == correta
                quiz["answers"][idx] = {"resposta": resposta, "correta": acertou}

                run_query(
                    "INSERT INTO question_attempts (question_id, subject_id, is_correct, timestamp) VALUES (?, ?, ?, ?)",
                    (int(q["id"]), sid, 1 if acertou else 0, datetime.now().isoformat()),
                )

                # Fila de prioridade: erro aumenta prioridade, acerto reduz
                nova_prioridade = float(q["priority"]) * (1.6 if not acertou else 0.7)
                nova_prioridade = max(0.3, min(nova_prioridade, 10))
                run_query("UPDATE questions SET priority = ? WHERE id = ?", (nova_prioridade, int(q["id"])))

                if acertou:
                    st.success("✅ Resposta correta!")
                else:
                    st.error(f"❌ Resposta incorreta. Gabarito: {correta}")
                if q["explanation"]:
                    st.info(f"📖 Comentário: {q['explanation']}")

                quiz["index"] += 1
                if quiz["index"] >= len(questoes):
                    quiz["finished"] = True
                    registrar_estudo(sid, len(questoes) * 2, "simulado")
                st.session_state.current_quiz = quiz

            st.button("➡️ Próxima questão", key=f"next_{idx}", on_click=lambda: None)

    if quiz and quiz.get("finished"):
        respostas = quiz["answers"]
        total = len(respostas)
        acertos = sum(1 for r in respostas.values() if r["correta"])
        erros = total - acertos
        pct = (acertos / total * 100) if total else 0

        st.divider()
        st.subheader("📊 Relatório de Desempenho do Simulado")
        c1, c2, c3 = st.columns(3)
        c1.metric("Percentual de Acertos", f"{pct:.1f}%")
        c2.metric("Acertos (absoluto)", acertos)
        c3.metric("Erros (absoluto)", erros)

        fig = px.pie(
            names=["Acertos", "Erros"], values=[acertos, erros],
            color=["Acertos", "Erros"], color_discrete_map={"Acertos": "#2ecc71", "Erros": "#e74c3c"},
        )
        st.plotly_chart(fig, use_container_width=True)

        if erros > 0:
            st.warning(
                f"⚠️ {erros} questão(ões) errada(s) foram adicionadas com prioridade "
                "elevada na fila de Revisões por Desempenho."
            )

        if st.button("🔁 Fazer novo simulado"):
            st.session_state.current_quiz = None
            st.rerun()

# =============================================================================
# PÁGINA 6 - CRONÔMETRO POMODORO
# =============================================================================
elif pagina == "🍅 Pomodoro":
    st.title("🍅 Cronômetro Pomodoro")
    st.caption("Registre seu tempo líquido de estudo diretamente no sistema.")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))

    col1, col2, col3 = st.columns(3)
    minutos_foco = col1.number_input("Duração do foco (min)", 5, 120, 25)
    minutos_pausa = col2.number_input("Duração da pausa (min)", 1, 60, 5)
    materia_pomodoro = col3.selectbox(
        "Matéria a registrar", subjects_df["name"].tolist() if not subjects_df.empty else ["Geral"]
    )

    duracao_atual = minutos_foco * 60 if st.session_state.pomodoro_mode == "foco" else minutos_pausa * 60

    placeholder_timer = st.empty()

    colb1, colb2, colb3 = st.columns(3)
    if colb1.button("▶️ Iniciar" if not st.session_state.pomodoro_running else "⏸️ Pausar"):
        if not st.session_state.pomodoro_running:
            st.session_state.pomodoro_start_ts = time.time()
            st.session_state.pomodoro_running = True
        else:
            st.session_state.pomodoro_running = False
        st.rerun()

    if colb2.button("⏹️ Resetar ciclo"):
        st.session_state.pomodoro_running = False
        st.session_state.pomodoro_start_ts = None
        st.session_state.pomodoro_mode = "foco"
        st.rerun()

    if colb3.button("✅ Concluir e registrar manualmente"):
        if not subjects_df.empty:
            sid = int(subjects_df.loc[subjects_df["name"] == materia_pomodoro, "id"].values[0])
            registrar_estudo(sid, minutos_foco, "pomodoro")
            st.success(f"{minutos_foco} minutos registrados em '{materia_pomodoro}'!")
        else:
            st.warning("Cadastre uma matéria antes de registrar o tempo.")

    # Loop de atualização do timer (padrão comum em apps Streamlit para "tempo real")
    if st.session_state.pomodoro_running and st.session_state.pomodoro_start_ts:
        decorrido = time.time() - st.session_state.pomodoro_start_ts
        restante = max(0, duracao_atual - decorrido)
        minutos, segundos = divmod(int(restante), 60)
        emoji = "🎯 FOCO" if st.session_state.pomodoro_mode == "foco" else "☕ PAUSA"
        placeholder_timer.markdown(f"## {emoji} — {minutos:02d}:{segundos:02d}")

        if restante <= 0:
            if st.session_state.pomodoro_mode == "foco":
                if not subjects_df.empty:
                    sid = int(subjects_df.loc[subjects_df["name"] == materia_pomodoro, "id"].values[0])
                    registrar_estudo(sid, minutos_foco, "pomodoro")
                st.session_state.pomodoro_cycle_count += 1
                st.session_state.pomodoro_mode = "pausa"
                st.toast("✅ Ciclo de foco concluído! Hora da pausa.")
            else:
                st.session_state.pomodoro_mode = "foco"
                st.toast("🔔 Pausa concluída! Hora de focar novamente.")
            st.session_state.pomodoro_start_ts = time.time()

        time.sleep(1)
        st.rerun()
    else:
        minutos, segundos = divmod(int(duracao_atual), 60)
        placeholder_timer.markdown(f"## ⏳ Pronto para iniciar — {minutos:02d}:{segundos:02d}")

    st.metric("Ciclos de foco concluídos hoje", st.session_state.pomodoro_cycle_count)

# =============================================================================
# PÁGINA 7 - RELATÓRIOS E CURVA DE EBBINGHAUS
# =============================================================================
elif pagina == "📊 Relatórios e Ebbinghaus":
    st.title("📊 Relatórios Semanais e Curva de Esquecimento")

    inicio_semana = date.today() - timedelta(days=7)
    log_df = df_query(
        "SELECT * FROM study_log WHERE log_date >= ?", (inicio_semana.isoformat(),)
    )

    if log_df.empty:
        st.info("Ainda não há dados de estudo registrados nos últimos 7 dias.")
    else:
        log_df["log_date"] = pd.to_datetime(log_df["log_date"])
        resumo_diario = log_df.groupby("log_date")["minutes"].sum().reset_index()
        fig = px.line(
            resumo_diario, x="log_date", y="minutes", markers=True,
            title="Minutos estudados nos últimos 7 dias", labels={"minutes": "Minutos", "log_date": "Data"},
        )
        st.plotly_chart(fig, use_container_width=True)

        subjects_all = df_query("SELECT id, name FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
        if not subjects_all.empty:
            log_com_nome = log_df.merge(subjects_all, left_on="subject_id", right_on="id", how="left")
            resumo_materia = log_com_nome.groupby("name")["minutes"].sum().reset_index()
            fig2 = px.bar(resumo_materia, x="name", y="minutes", title="Distribuição de tempo por matéria (7 dias)",
                          labels={"name": "Matéria", "minutes": "Minutos"})
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("💡 Sugestões estratégicas")
        subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
        if not subjects_df.empty:
            for _, row in subjects_df.iterrows():
                desempenho = calcular_desempenho_materia(row["id"])
                if desempenho < 0.5:
                    st.warning(
                        f"📌 **{row['name']}**: desempenho de {desempenho*100:.0f}%. "
                        "Priorize revisões e refaça questões desta matéria em breve."
                    )
                elif desempenho > 0.85:
                    st.success(
                        f"🌟 **{row['name']}**: ótimo desempenho ({desempenho*100:.0f}%). "
                        "Considere espaçar mais as revisões e focar tempo em outras matérias."
                    )

    st.divider()
    st.subheader("🧠 Curva de Esquecimento de Ebbinghaus")
    st.caption(
        "A retenção de memória cai exponencialmente com o tempo sem revisão. "
        "O CRONOMODY agenda revisões nos pontos ideais para 'resetar' a curva antes do esquecimento crítico."
    )

    dias = np.linspace(0, 30, 200)
    retencao_sem_revisao = 100 * np.exp(-dias / 5)

    fig_ebb = go.Figure()
    fig_ebb.add_trace(go.Scatter(x=dias, y=retencao_sem_revisao, mode="lines", name="Sem revisão", line=dict(color="red")))

    pontos_revisao = [1, 7, 16, 30]
    retencao_com_revisao = []
    nivel = 100
    ultimo_dia = 0
    xs, ys = [], []
    for d in dias:
        if pontos_revisao and d >= pontos_revisao[0]:
            nivel = 100
            ultimo_dia = pontos_revisao.pop(0)
        val = nivel * np.exp(-(d - ultimo_dia) / 5)
        xs.append(d)
        ys.append(val)
    fig_ebb.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="Com revisões espaçadas (SM-2)", line=dict(color="green")))

    for marco in [1, 7, 16, 30]:
        fig_ebb.add_vline(x=marco, line_dash="dot", line_color="gray")

    fig_ebb.update_layout(
        xaxis_title="Dias", yaxis_title="Retenção de memória (%)",
        title="Impacto das revisões espaçadas na retenção de memória",
        height=400,
    )
    st.plotly_chart(fig_ebb, use_container_width=True)

# =============================================================================
# RODAPÉ
# =============================================================================
st.sidebar.divider()
st.sidebar.caption("CRONOMODY © 2026 — Estude com método, não com sorte.")
