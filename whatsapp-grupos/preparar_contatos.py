#!/usr/bin/env python3
"""
Lê uma planilha de contatos (.xlsx) e gera um arquivo contatos.json,
pronto para o script criar-grupos.js.

O JSON de saída tem o formato:
{
  "grupos": [
    { "nome": "Clientes - AUGUSTO", "contatos": [ {"nome": "...", "telefone": "5551999999999"}, ... ] },
    ...
  ]
}

Uso:
  # Um grupo por vendedor (coluna "Comercial"), usando a aba "Por Comercial":
  python3 preparar_contatos.py planilha.xlsx \
      --aba "Por Comercial" --col-nome "Nome" --col-tel "tel" \
      --col-grupo "Comercial" --prefixo "Clientes - "

  # Um único grupo com todo mundo da aba "tel":
  python3 preparar_contatos.py planilha.xlsx \
      --aba "tel" --col-nome "Nome Completo" --col-tel "Telefone" \
      --nome-grupo "Clientes Setembro 2026"

Observações sobre telefones (Brasil):
  - Números são normalizados para o formato internacional: 55 + DDD + número.
  - Números fixos/antigos com 10 dígitos (DDD + 8) recebem uma marcação para que
    o criar-grupos.js tente resolver a variação com o 9º dígito no WhatsApp.
  - Linhas sem telefone válido são ignoradas (e listadas no relatório).
"""

import argparse
import json
import re
import sys
import unicodedata

try:
    import pandas as pd
except ImportError:
    sys.exit("Falta a biblioteca pandas. Instale com: pip install pandas openpyxl")


DDI_BRASIL = "55"


def so_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def normalizar_telefone(bruto):
    """
    Recebe um telefone em qualquer formato e devolve um dict:
      { "e164": "5551999999999", "incerto": False }
    ou None se não for possível montar um número plausível.

    "incerto" = True quando o número tem 10 dígitos (DDD + 8), caso em que
    pode faltar o 9º dígito de celular — o criar-grupos.js confirmará no WhatsApp.
    """
    d = so_digitos(bruto)
    if not d:
        return None

    # Remove um "0" de operadora/DDD antes do DDD, se veio colado.
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]

    # Já veio com DDI 55?
    if d.startswith(DDI_BRASIL) and len(d) in (12, 13):
        nacional = d[2:]
    else:
        nacional = d

    # nacional esperado: DDD (2) + assinante (8 ou 9)
    if len(nacional) == 11:  # DDD + 9 dígitos (celular moderno) -> ok
        return {"e164": DDI_BRASIL + nacional, "incerto": False}
    if len(nacional) == 10:  # DDD + 8 dígitos (fixo, ou celular sem o 9) -> incerto
        return {"e164": DDI_BRASIL + nacional, "incerto": True}

    # Qualquer outro tamanho é considerado inválido/malformado.
    return None


def limpar_nome(nome) -> str:
    return re.sub(r"\s+", " ", str(nome or "").strip())


def slug(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "_", t.strip()).upper()


def main():
    p = argparse.ArgumentParser(description="Prepara contatos.json a partir de uma planilha.")
    p.add_argument("planilha", help="Caminho do arquivo .xlsx")
    p.add_argument("--aba", required=True, help="Nome da aba/planilha a ler")
    p.add_argument("--col-nome", required=True, help="Nome da coluna com o nome do contato")
    p.add_argument("--col-tel", required=True, help="Nome da coluna com o telefone")
    p.add_argument("--col-grupo", help="Coluna que define o grupo (ex.: Comercial). Se ausente, cria um único grupo.")
    p.add_argument("--prefixo", default="", help="Prefixo do nome de cada grupo (usado com --col-grupo)")
    p.add_argument("--nome-grupo", help="Nome do grupo único (usado quando NÃO há --col-grupo)")
    p.add_argument("--comerciais", help="(Opcional) JSON {\"NOME_DO_COMERCIAL\": \"telefone\"} para incluir cada comercial no próprio grupo")
    p.add_argument("--fixos", help="(Opcional) JSON [{\"nome\": \"...\", \"telefone\": \"...\"}] de contatos que entram em TODOS os grupos")
    p.add_argument("--saida", default="contatos.json", help="Arquivo JSON de saída (padrão: contatos.json)")
    args = p.parse_args()

    if not args.col_grupo and not args.nome_grupo:
        p.error("informe --col-grupo (vários grupos) OU --nome-grupo (um único grupo).")

    df = pd.read_excel(args.planilha, sheet_name=args.aba)

    for col in [args.col_nome, args.col_tel] + ([args.col_grupo] if args.col_grupo else []):
        if col not in df.columns:
            p.error(f'Coluna "{col}" não existe na aba "{args.aba}". Colunas: {list(df.columns)}')

    # Telefones dos comerciais (opcional): {"EDUARDO": "51 9376-4571", ...}
    comerciais = {}
    if args.comerciais:
        with open(args.comerciais, encoding="utf-8") as f:
            bruto = json.load(f)
        for chave, tel in bruto.items():
            if not str(tel or "").strip():
                continue  # comercial sem telefone preenchido: ignora
            norm = normalizar_telefone(tel)
            if norm:
                comerciais[limpar_nome(chave)] = norm
            else:
                print(f'Aviso: telefone do comercial "{chave}" inválido, ignorado: {tel}')

    # Contatos fixos (entram em TODOS os grupos): [{"nome": "...", "telefone": "..."}]
    fixos = []
    if args.fixos:
        with open(args.fixos, encoding="utf-8") as f:
            for item in json.load(f):
                if not str(item.get("telefone") or "").strip():
                    continue
                norm = normalizar_telefone(item["telefone"])
                if norm:
                    fixos.append({
                        "nome": limpar_nome(item.get("nome")) or "Contato fixo",
                        "telefone": norm["e164"],
                        "incerto": norm["incerto"],
                    })
                else:
                    print(f'Aviso: telefone do contato fixo "{item.get("nome")}" inválido, ignorado: {item["telefone"]}')

    grupos = {}          # nome_grupo -> lista de contatos
    vistos = set()       # dedup por (grupo, e164)
    ignorados = []       # linhas sem telefone válido
    incertos = 0

    for _, linha in df.iterrows():
        nome = limpar_nome(linha[args.col_nome])
        if not nome or nome.lower() == "nan":
            continue

        tel = normalizar_telefone(linha[args.col_tel])
        if tel is None:
            ignorados.append({"nome": nome, "telefone_original": str(linha[args.col_tel])})
            continue
        if tel["incerto"]:
            incertos += 1

        if args.col_grupo:
            chave = limpar_nome(linha[args.col_grupo]) or "SEM_GRUPO"
            nome_grupo = f"{args.prefixo}{chave}"
        else:
            nome_grupo = args.nome_grupo

        dedup_key = (nome_grupo, tel["e164"])
        if dedup_key in vistos:
            continue
        vistos.add(dedup_key)

        grupos.setdefault(nome_grupo, []).append(
            {"nome": nome, "telefone": tel["e164"], "incerto": tel["incerto"]}
        )

    # Inclui cada comercial no próprio grupo (se um telefone foi fornecido).
    comerciais_incluidos = 0
    if comerciais and args.col_grupo:
        for chave, tel in comerciais.items():
            nome_grupo = f"{args.prefixo}{chave}"
            if nome_grupo not in grupos:
                continue  # esse comercial não tem clientes na planilha
            if any(c["telefone"] == tel["e164"] for c in grupos[nome_grupo]):
                continue  # já está no grupo
            grupos[nome_grupo].insert(
                0,
                {"nome": f"{chave} (comercial)", "telefone": tel["e164"], "incerto": tel["incerto"]},
            )
            comerciais_incluidos += 1

    # Adiciona os contatos fixos em TODOS os grupos (sem duplicar).
    fixos_incluidos = 0
    for fixo in fixos:
        for nome_grupo, lista in grupos.items():
            if any(c["telefone"] == fixo["telefone"] for c in lista):
                continue
            lista.append(dict(fixo))
            fixos_incluidos += 1

    saida = {
        "grupos": [
            {"nome": g, "contatos": c} for g, c in sorted(grupos.items())
        ]
    }

    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    # Relatório
    total = sum(len(g["contatos"]) for g in saida["grupos"])
    print(f'Arquivo gerado: {args.saida}')
    print(f'Grupos: {len(saida["grupos"])} | Contatos válidos: {total} | '
          f'Incertos (10 díg.): {incertos} | Ignorados sem telefone: {len(ignorados)}')
    if comerciais:
        print(f'Comerciais incluídos em seus grupos: {comerciais_incluidos}')
    if fixos:
        print(f'Contatos fixos em todos os grupos: {len(fixos)} '
              f'({", ".join(x["nome"] for x in fixos)})')
    print()
    for g in saida["grupos"]:
        print(f'  - {g["nome"]}: {len(g["contatos"])} contatos')

    if ignorados:
        print()
        print(f'{len(ignorados)} linha(s) sem telefone válido (não entram em nenhum grupo). '
              f'Exemplos:')
        for item in ignorados[:10]:
            print(f'    * {item["nome"]}  ({item["telefone_original"]})')


if __name__ == "__main__":
    main()
