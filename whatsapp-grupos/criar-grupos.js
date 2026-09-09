/**
 * criar-grupos.js
 *
 * Cria grupos de WhatsApp a partir de um arquivo contatos.json
 * (gerado por preparar_contatos.py) usando a biblioteca whatsapp-web.js.
 *
 * Como funciona:
 *   1. Abre uma sessão do WhatsApp Web (mostra um QR Code no terminal na 1ª vez).
 *   2. Para cada grupo do JSON, confirma quais números existem no WhatsApp.
 *   3. Cria o grupo e adiciona os membros em lotes, com pausas entre as ações.
 *   4. Para quem não pôde ser adicionado direto (privacidade), gera o link de convite.
 *
 * Uso:
 *   node criar-grupos.js contatos.json                 # cria de verdade
 *   node criar-grupos.js contatos.json --simular       # só mostra o que faria (nada é criado)
 *
 * IMPORTANTE — leia o README.md. Isto usa uma biblioteca NÃO-oficial. Criar muitos
 * grupos / adicionar muita gente rápido pode levar ao BANIMENTO do número. Use com
 * calma, de preferência com um número secundário, e comece com --simular.
 */

const fs = require("fs");
const path = require("path");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

// ------------------------- Configurações de ritmo -------------------------
// Ajuste com cuidado. Valores maiores = mais lento, porém mais seguro.
const CFG = {
  membrosPorLote: 8,          // quantos números adicionar por vez ao criar/incluir
  pausaEntreLotesMs: 8000,    // pausa entre lotes de membros
  pausaEntreGruposMs: 20000,  // pausa entre a criação de um grupo e o próximo
  pausaVerificacaoMs: 1200,   // pausa entre cada checagem de número no WhatsApp
  criarComPrimeiroLote: true, // cria o grupo já com o 1º lote; adiciona o resto depois
};
// --------------------------------------------------------------------------

const arquivo = process.argv[2] || "contatos.json";
const SIMULAR = process.argv.includes("--simular");

const dorme = (ms) => new Promise((r) => setTimeout(r, ms));

function carregarContatos(caminho) {
  if (!fs.existsSync(caminho)) {
    console.error(`Arquivo não encontrado: ${caminho}`);
    console.error('Gere-o antes com: python3 preparar_contatos.py ...');
    process.exit(1);
  }
  const dados = JSON.parse(fs.readFileSync(caminho, "utf-8"));
  if (!dados.grupos || !Array.isArray(dados.grupos)) {
    console.error('JSON inválido: esperado um objeto com a chave "grupos" (array).');
    process.exit(1);
  }
  return dados.grupos;
}

/**
 * Resolve o ID do WhatsApp de um número, tratando a variação do 9º dígito
 * em celulares brasileiros. Retorna o "serialized id" (ex.: 5551999999999@c.us)
 * ou null se o número não tiver WhatsApp.
 */
async function resolverId(client, contato) {
  const candidatos = [contato.telefone];

  // Se o número é "incerto" (10 dígitos: DDD + 8), tenta também a versão com o 9.
  if (contato.incerto) {
    const m = contato.telefone.match(/^55(\d{2})(\d{8})$/);
    if (m) candidatos.push(`55${m[1]}9${m[2]}`);
  }

  for (const numero of candidatos) {
    try {
      const id = await client.getNumberId(numero);
      if (id) return id._serialized;
    } catch (_) {
      /* ignora e tenta o próximo candidato */
    }
    await dorme(CFG.pausaVerificacaoMs);
  }
  return null;
}

function linhaRelatorio(rel) {
  fs.writeFileSync(
    path.join(__dirname, "relatorio-grupos.json"),
    JSON.stringify(rel, null, 2),
    "utf-8"
  );
}

async function processarGrupo(client, grupo, relatorio) {
  console.log(`\n=== Grupo: ${grupo.nome} (${grupo.contatos.length} contatos) ===`);
  const registro = {
    grupo: grupo.nome,
    adicionados: [],
    semWhatsapp: [],
    conviteNecessario: [],
    linkConvite: null,
    erro: null,
  };

  // 1) Confirma quais números existem no WhatsApp.
  const ids = [];
  for (const c of grupo.contatos) {
    const id = SIMULAR ? `${c.telefone}@c.us` : await resolverId(client, c);
    if (id) {
      ids.push({ id, contato: c });
    } else {
      console.log(`  · sem WhatsApp: ${c.nome} (${c.telefone})`);
      registro.semWhatsapp.push(c);
    }
  }

  if (ids.length === 0) {
    console.log("  Nenhum número válido no WhatsApp. Grupo não criado.");
    registro.erro = "nenhum número com WhatsApp";
    relatorio.push(registro);
    return;
  }

  if (SIMULAR) {
    console.log(`  [SIMULAÇÃO] Criaria o grupo com ${ids.length} membro(s).`);
    registro.adicionados = ids.map((x) => x.contato);
    relatorio.push(registro);
    return;
  }

  // 2) Cria o grupo com o primeiro lote de membros.
  const lotes = [];
  for (let i = 0; i < ids.length; i += CFG.membrosPorLote) {
    lotes.push(ids.slice(i, i + CFG.membrosPorLote));
  }

  let chat;
  try {
    const primeiro = lotes.shift();
    const res = await client.createGroup(
      grupo.nome,
      primeiro.map((x) => x.id)
    );
    // Em versões recentes, createGroup devolve um objeto com gid e "missingParticipants".
    const gid = typeof res === "object" ? res.gid?._serialized || res.gid : res;
    chat = await client.getChatById(gid);
    registrarResultadoLote(primeiro, res, registro);
    console.log(`  Grupo criado. Membros no 1º lote: ${primeiro.length}`);
  } catch (e) {
    console.log(`  ERRO ao criar o grupo: ${e.message}`);
    registro.erro = e.message;
    relatorio.push(registro);
    return;
  }

  // 3) Adiciona os lotes restantes.
  for (const lote of lotes) {
    await dorme(CFG.pausaEntreLotesMs);
    try {
      const res = await chat.addParticipants(lote.map((x) => x.id));
      registrarResultadoLote(lote, res, registro);
      console.log(`  + ${lote.length} membro(s) adicionado(s).`);
    } catch (e) {
      console.log(`  ERRO ao adicionar lote: ${e.message}`);
      lote.forEach((x) => registro.conviteNecessario.push(x.contato));
    }
  }

  // 4) Se alguém precisa de convite, gera o link do grupo.
  if (registro.conviteNecessario.length > 0) {
    try {
      const code = await chat.getInviteCode();
      registro.linkConvite = `https://chat.whatsapp.com/${code}`;
      console.log(`  Link de convite (para quem não pôde ser adicionado): ${registro.linkConvite}`);
    } catch (e) {
      console.log(`  Não foi possível gerar o link de convite: ${e.message}`);
    }
  }

  relatorio.push(registro);
}

/**
 * addParticipants/createGroup podem devolver um mapa por participante com um
 * "code" de status (200 = ok; 403/408 costumam indicar privacidade => convite).
 */
function registrarResultadoLote(lote, resultado, registro) {
  const porId =
    resultado && typeof resultado === "object" && !resultado.gid
      ? resultado
      : resultado?.participants || {};

  for (const x of lote) {
    const info = porId?.[x.id];
    const code = info?.code ?? info?.statusCode;
    if (code && code !== 200) {
      registro.conviteNecessario.push(x.contato);
    } else {
      registro.adicionados.push(x.contato);
    }
  }
}

async function main() {
  const grupos = carregarContatos(arquivo);
  const totalContatos = grupos.reduce((s, g) => s + g.contatos.length, 0);

  console.log(`Arquivo: ${arquivo}`);
  console.log(`Grupos a criar: ${grupos.length} | Total de contatos: ${totalContatos}`);
  if (SIMULAR) console.log("MODO SIMULAÇÃO: nada será criado no WhatsApp.\n");

  const client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, ".wwebjs_auth") }),
    puppeteer: {
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  });

  client.on("qr", (qr) => {
    console.log("\nEscaneie o QR Code abaixo no WhatsApp (Aparelhos conectados):\n");
    qrcode.generate(qr, { small: true });
  });

  client.on("authenticated", () => console.log("Autenticado. Sessão salva em .wwebjs_auth/"));
  client.on("auth_failure", (m) => console.error("Falha de autenticação:", m));

  client.on("ready", async () => {
    console.log("Conectado ao WhatsApp!\n");
    const relatorio = [];
    try {
      for (let i = 0; i < grupos.length; i++) {
        await processarGrupo(client, grupos[i], relatorio);
        linhaRelatorio(relatorio); // salva progresso a cada grupo
        if (i < grupos.length - 1 && !SIMULAR) {
          console.log(`  (aguardando ${CFG.pausaEntreGruposMs / 1000}s antes do próximo grupo...)`);
          await dorme(CFG.pausaEntreGruposMs);
        }
      }
    } finally {
      linhaRelatorio(relatorio);
      console.log("\nConcluído. Relatório salvo em relatorio-grupos.json");
      await client.destroy();
      process.exit(0);
    }
  });

  await client.initialize();
}

main().catch((e) => {
  console.error("Erro fatal:", e);
  process.exit(1);
});
