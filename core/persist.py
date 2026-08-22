import base64
import json
import os
import requests


REPO = "Betel06/bot"
CAMINHO = "estado.json"
API_URL = "https://api.github.com/repos/{}/contents/{}".format(REPO, CAMINHO)


def _headers():
    return {
        "Authorization": "token " + os.environ.get("GITHUB_TOKEN", ""),
        "User-Agent": "bots-cripto",
        "Accept": "application/vnd.github+json",
    }


def configurado():
    return bool(os.environ.get("GITHUB_TOKEN"))


def carregar_estado():
    """Retorna o dict do estado remoto, ou {} se indisponivel."""
    try:
        r = requests.get(API_URL, headers=_headers(), timeout=15)
        if r.status_code != 200:
            return {}
        conteudo = base64.b64decode(r.json().get("content") or "").decode("utf-8")
        dados = json.loads(conteudo or "{}")
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def salvar_secao(secao, dados, tentativas=3):
    """
    Faz merge da secao no estado remoto (GET -> merge -> PUT).
    Suporta concorrencia entre os dois servicos (retry em 409).
    Retorna True se salvou.
    """
    for tentativa in range(tentativas):
        try:
            r = requests.get(API_URL, headers=_headers(), timeout=15)
            sha = None
            estado = {}
            if r.status_code == 200:
                sha = r.json().get("sha")
                conteudo = base64.b64decode(r.json().get("content") or "").decode("utf-8")
                bruto = json.loads(conteudo or "{}")
                estado = bruto if isinstance(bruto, dict) else {}
            elif r.status_code != 404:
                return False

            atual = estado.get(secao)
            if isinstance(atual, dict) and isinstance(dados, dict):
                atual.update(dados)
            else:
                estado[secao] = dados

            corpo = {
                "message": "sync estado ({})".format(secao),
                "content": base64.b64encode(
                    json.dumps(estado, ensure_ascii=False).encode("utf-8")
                ).decode("ascii"),
            }
            if sha:
                corpo["sha"] = sha

            resp = requests.put(API_URL, headers=_headers(), json=corpo, timeout=25)
            if resp.status_code in (200, 201):
                return True
            if resp.status_code == 409:
                continue
            return False
        except Exception:
            if tentativa == tentativas - 1:
                return False
    return False
