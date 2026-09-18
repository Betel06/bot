#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IA CONSELHO - consulta todas as IAs disponiveis (Gemini, OpenRouter free,
Claude via OmniRoute) em paralelo sobre um problema e consolida um veredito.

Uso:
    python conselho.py "seu problema ou pergunta"
    python conselho.py --presidente gemini "pergunta"
    python conselho.py --so-ler /path/arquivo.txt   # ler tarefa de arquivo

Variaveis de ambiente (credentials.env):
    GEMINI_API_KEY      -> Gemini (AI Studio gratis)
    OPENROUTER_API_KEY  -> OpenRouter (:free)
    (Claude via OmniRoute nao precisa de env, usa o gateway local)
"""

import os
import json
import sys
import time
import threading

try:
    import requests
except ImportError:
    print("ERRO: instale 'requests' (pip install requests)")
    sys.exit(1)

CREDENTIALS = os.path.expanduser(r"~\.config\opencode\credentials.env")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FREE = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "cohere/north-mini-code:free",
]
OMNIROUTE_URL = "http://127.0.0.1:20128/v1/chat/completions"
OMNIROUTE_HEADERS = {
    "Authorization": "Bearer sk-7b15723d6d4fdcc7-467f61-a66ed103",
    "Content-Type": "application/json",
}
OMNIROUTE_MODEL = "openrouter/auto"
TIMEOUT = 90
LOCK = threading.Lock()


def _carregar_credenciais():
    if not os.path.exists(CREDENTIALS):
        return
    with open(CREDENTIALS, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip('"').strip("'")


def _print_ok(*a):
    with LOCK:
        print(*a)


def _gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return "Gemini", None, "GEMINI_API_KEY ausente"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }
    headers = {"x-goog-api-key": key}
    ultimo = "nenhum modelo"
    for modelo in GEMINI_MODELS:
        url = GEMINI_URL.format(model=modelo)
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            ultimo = "{}: {}".format(modelo, e)
            continue
        if resp.status_code == 200:
            try:
                txt = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return "Gemini ({})".format(modelo), txt, None
            except Exception as e:
                ultimo = "{}: parse falhou: {}".format(modelo, e)
                continue
        if resp.status_code == 429:
            ultimo = "{}: cota diaria esgotada (HTTP 429)".format(modelo)
            break
        ultimo = "{}: HTTP {}: {}".format(modelo, resp.status_code, resp.text[:150])
    return "Gemini", None, ultimo


def _openrouter(prompt):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return "OpenRouter", None, "OPENROUTER_API_KEY ausente"
    body = {
        "model": None,
        "messages": [
            {"role": "system", "content": "Voce e um especialista dando o melhor conselho possivel."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
    }
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    ultimo = "nenhum modelo"
    for modelo in OPENROUTER_FREE:
        body["model"] = modelo
        try:
            resp = requests.post(OPENROUTER_URL, json=body, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            ultimo = "{}: {}".format(modelo, e)
            continue
        if resp.status_code == 200:
            try:
                txt = resp.json()["choices"][0]["message"]["content"]
                return "OpenRouter ({})".format(modelo), txt, None
            except Exception as e:
                ultimo = "{}: parse falhou: {}".format(modelo, e)
                continue
        if resp.status_code == 401 and "credits" in resp.text.lower():
            ultimo = "{}: sem creditos".format(modelo)
            continue
        ultimo = "{}: HTTP {}: {}".format(modelo, resp.status_code, resp.text[:150])
    return "OpenRouter", None, ultimo


def _sse_text(resp):
    """Le uma resposta stream (SSE) e junta os deltas de conteudo em texto."""
    partes = []
    for linha in resp.iter_lines(decode_unicode=True):
        if not linha or not linha.startswith("data:"):
            continue
        dado = linha[5:].strip()
        if dado == "[DONE]":
            break
        try:
            obj = json.loads(dado)
        except Exception:
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        c = delta.get("content")
        if c:
            partes.append(c)
    return "".join(partes).strip()


def _omniroute(prompt):
    body = {
        "model": OMNIROUTE_MODEL,
        "messages": [
            {"role": "system", "content": "Voce e um especialista dando o melhor conselho possivel."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
        "stream": True,
    }
    try:
        resp = requests.post(OMNIROUTE_URL, json=body, headers=OMNIROUTE_HEADERS,
                             timeout=TIMEOUT, stream=True)
    except Exception as e:
        return "Claude/OmniRoute", None, "gateway offline: {}".format(e)
    if resp.status_code != 200:
        return "Claude/OmniRoute", None, "HTTP {}: {}".format(resp.status_code, resp.text[:150])
    try:
        txt = _sse_text(resp)
    except Exception as e:
        return "Claude/OmniRoute", None, "parse falhou: {}".format(e)
    if not txt:
        return "Claude/OmniRoute", None, "resposta vazia"
    return "Claude/OmniRoute", txt, None


CONSELHEIROS = [("Gemini", _gemini), ("OpenRouter", _openrouter), ("Claude", _omniroute)]


def _sistema_para(presidente):
    return (
        "Voce e o PRESIDENTE de um conselho de IAs. Abaixo estao as respostas de "
        "cada conselheiro sobre o problema. Analise todas, aponte divergencias e "
        "pontos fortes/fragilidades de cada visao, e produza UM veredito final "
        "coeso e acionavel, o mais inteligente e equilibrado possivel. "
        "Seja direto e pratico."
    )


def _convocar(prompt):
    resultados = {}
    caixas = {}

    def rodar(nome, fn):
        try:
            label, texto, erro = fn(prompt)
            caixas[nome] = (nome, label, texto, erro)
        except Exception as e:
            caixas[nome] = (nome, nome, None, "falha interna: {}".format(e))

    threads = []
    for nome, fn in CONSELHEIROS:
        caixas[nome] = None
        t = threading.Thread(target=rodar, args=(nome, fn), daemon=True)
        threads.append(t)
        t.start()

    # aguarda com prazo global; daemon threads penduradas nao seguram o exit
    limite = time.time() + 110
    while time.time() < limite:
        if all(caixas[n] is not None for n, _ in CONSELHEIROS):
            break
        time.sleep(0.3)

    for nome, _ in CONSELHEIROS:
        r = caixas[nome]
        if r is None:
            resultados[nome] = (nome, nome, None, "timeout (demorou demais)")
        else:
            resultados[nome] = r

    ordem = [n for n, _ in CONSELHEIROS]
    return [resultados[n] for n in ordem]


def _presidente(prompt, respostas_dos_conselheiros, presidente):
    textos = []
    for _, conselheiro, texto, erro in respostas_dos_conselheiros:
        if texto:
            textos.append("### {}\n{}".format(conselheiro, texto))
        else:
            textos.append("### {} (SEM RESPOSTA: {})".format(conselheiro, erro))
    bloco = "\n\n".join(textos)

    if presidente == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return "Sem chave Gemini para presidir."
        sysprompt = _sistema_para(presidente)
        body = {
            "contents": [
                {"parts": [{"text": sysprompt}]},
                {"parts": [{"text": "PROBLEMA:\n" + prompt + "\n\nRESPOSTAS DOS CONSELHEIROS:\n" + bloco}]},
            ],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
        }
        for modelo in GEMINI_MODELS:
            try:
                resp = requests.post(GEMINI_URL.format(model=modelo), json=body,
                                     headers={"x-goog-api-key": key}, timeout=TIMEOUT)
            except Exception as e:
                continue
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return "Presidente Gemini falhou."
    else:
        sysprompt = _sistema_para(presidente)
        mensagens = [
            {"role": "system", "content": sysprompt},
            {"role": "user", "content": "PROBLEMA:\n" + prompt + "\n\nRESPOSTAS DOS CONSELHEIROS:\n" + bloco},
        ]
        payload = {"messages": mensagens, "max_tokens": 2048}
        if presidente == "omniroute":
            payload["model"] = OMNIROUTE_MODEL
            payload["stream"] = True
            resp = requests.post(OMNIROUTE_URL, json=payload, headers=OMNIROUTE_HEADERS,
                                 timeout=TIMEOUT, stream=True)
            if resp.status_code != 200:
                return "Presidente OmniRoute falhou: HTTP {}\n{}".format(resp.status_code, resp.text[:200])
            try:
                return _sse_text(resp)
            except Exception as e:
                return "Presidente OmniRoute parse falhou: {}".format(e)
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            return "Sem chave OpenRouter para presidir."
        payload["model"] = "nvidia/nemotron-3-ultra-550b-a55b:free"
        resp = requests.post(OPENROUTER_URL, json=payload,
                             headers={"Authorization": "Bearer " + key,
                                      "Content-Type": "application/json"}, timeout=TIMEOUT)
        if resp.status_code != 200:
            return "Presidente OpenRouter falhou: HTTP {}: {}".format(resp.status_code, resp.text[:200])
        return resp.json()["choices"][0]["message"]["content"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _carregar_credenciais()

    args = sys.argv[1:]
    presidente = "omniroute"  # default: Claude via gateway (mais forte)
    if "--presidente" in args:
        i = args.index("--presidente")
        presidente = args[i + 1].lower()
        del args[i:i + 2]
    if presidente not in ("gemini", "omniroute", "openrouter"):
        print("Presidente invalido: use gemini, omniroute ou openrouter")
        sys.exit(1)

    if args and args[0] == "--so-ler":
        with open(args[1], "r", encoding="utf-8") as f:
            prompt = f.read().strip()
    elif args:
        prompt = " ".join(args)
    else:
        print("Uso: python conselho.py \"sua pergunta\"")
        sys.exit(1)

    print("=" * 62)
    print("IA CONSELHO - presidente: {}".format(presidente.upper()))
    print("=" * 62)
    print("PROBLEMA:\n{}\n".format(prompt))
    print("-" * 62)

    t0 = time.time()
    respostas = _convocar(prompt)

    for nome, conselheiro, texto, erro in respostas:
        print("\n>>> {} [{}]".format(nome.upper(), conselheiro))
        if texto:
            print(texto.strip())
        else:
            print("(SEM RESPOSTA) {}".format(erro))
        print("\n" + "-" * 62)

    print("\n>>> CONSOLIDANDO VEREDITO DO PRESIDENTE ({}s)...".format(int(time.time() - t0)))
    caixa = {}

    def _pres_runner():
        caixa["out"] = _presidente(prompt, respostas, presidente)

    pt = threading.Thread(target=_pres_runner, daemon=True)
    pt.start()
    pt.join(timeout=150)
    veredito = caixa.get("out", "(presidente nao respondeu no prazo)")
    print("\n########## VEREDITO DO CONSELHO ({}) ##########\n{}".format(presidente.upper(), veredito.strip()))
    print("\n(concluido em {}s)".format(int(time.time() - t0)))


if __name__ == "__main__":
    main()
