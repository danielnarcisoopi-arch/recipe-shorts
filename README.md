# Panela — receitas em Shorts

Projeto autónomo para criar e publicar seis vídeos verticais por dia. **Não altera o repositório, os segredos nem o workflow de CS2.** Instale esta pasta num repositório GitHub separado para as receitas.

Cada Short é montado a partir de uma receita diferente, com título, ingredientes, passos e narração traduzidos para português europeu, fotografias reais dos ingredientes e crédito de cada imagem e da fonte na descrição. Para aumentar a taxa de imagens encontradas, pesquisa primeiro fotografias no Pexels quando a chave opcional está configurada e, em seguida, no Wikimedia Commons; normaliza e valida cada ficheiro antes de o usar. O ecrã final procura e mostra uma fotografia do prato pronto. Se não encontrar uma fotografia utilizável, indica isso no próprio ecrã em vez de apresentar uma imagem inventada. O grafismo usa fotografias em cartões, texto em áreas separadas, maior contraste, indicação de progresso e movimento suave. O vídeo é 1080×1920, H.264/AAC e tem menos de 60 segundos. O gerador nunca completa ingredientes, temperaturas ou tempos que não estejam na receita; recusa fontes malformadas ou guiões fora do limite.

## Biblioteca de receitas

O projeto consulta o [Open Recipe Archive](https://github.com/AdamBouhmad/open-recipe-archive), que declara 54.843 receitas históricas em 31 coleções, com autor, livro, ano, URL e licença por registo. O workflow descarrega as coleções configuradas (`Portugal` e `Brazil` por omissão), importa apenas registos identificados como domínio público/CC0/Unlicense e atualiza a biblioteca semanalmente. O SQLite guarda o histórico para não repetir uma receita já publicada. Os metadados de proveniência ficam associados a cada vídeo.

São receitas históricas; as instruções podem usar medidas ou práticas antigas. A descrição do Short pede que se confirmem alergénios, temperaturas internas e conservação. A seleção exige ingredientes e passos estruturados. Se não houver uma receita elegível ainda não usada, o workflow falha sem inventar uma.

## Publicação diária

O GitHub Actions verifica o relógio uma vez por hora e só publica às **08:00, 11:00, 14:00, 17:00, 20:00 e 22:00**, hora de Lisboa. `ZoneInfo(Europe/Lisbon)` trata a mudança entre hora de inverno e verão. O grupo de concorrência impede duas publicações simultâneas; o SQLite regista o horário e a receita enviados para impedir duplicados em reexecuções. Como o GitHub pode atrasar execuções agendadas, os horários são janelas-alvo, não uma garantia ao minuto.

## Instalar sem tocar no CS2

1. Descarregue este projeto e crie **um repositório GitHub novo**, por exemplo `recipe-shorts`. Envie os ficheiros desta pasta para esse repositório.
2. No repositório novo, abra **Settings → Secrets and variables → Actions**.
3. Crie o secret `YOUTUBE_TOKEN_JSON` com o conteúdo integral de `token-recipes.json` (passos OAuth abaixo).
4. Crie a variável `EXPECTED_YOUTUBE_CHANNEL_ID` com o ID do canal de receitas (começa normalmente por `UC`). O workflow bloqueia o upload se a identidade OAuth e este ID não coincidirem.
5. Opcional: crie o secret `PEXELS_API_KEY` com uma chave da [API do Pexels](https://www.pexels.com/api/) para priorizar a biblioteca de fotografias de comida do Pexels. Sem essa chave, o projeto pesquisa no Wikimedia Commons sem credenciais.
6. Em **Settings → Actions → General**, permita ao workflow ler e escrever no repositório (a permissão `contents: write` mantém o catálogo e o histórico entre execuções).
7. Confirme em **Actions** que o workflow “Recipe Shorts · six daily editions” está ativo.

Todos estes valores ficam apenas no repositório de receitas. **Não substitua o segredo do repositório CS2 nem edite os ficheiros do projeto CS2.** Pode reutilizar o mesmo OAuth Client JSON da Google Cloud, mas gere e guarde um token separado para o canal de receitas.

## Autorizar o canal novo uma vez

É necessária uma autorização inicial do YouTube. O workflow renova o token de acesso automaticamente. Para não ter de repetir a autorização semanalmente, não deixes o consentimento OAuth em **Testing**: a documentação Google indica que refresh tokens emitidos para apps externas nesse estado expiram ao fim de sete dias. Publica o ecrã OAuth em **Production** e conclui qualquer verificação que a Google pedir; os tokens continuam revogáveis ou sujeitos às regras de segurança da conta.

1. Na Google Cloud Console, use um projeto com **YouTube Data API v3** ativa e crie/obtenha um OAuth Client ID do tipo **Desktop app**. Descarregue o JSON.
2. Num computador com Python 3.11+, FFmpeg e acesso ao browser, coloque esse ficheiro nesta pasta com o nome `client_secret.json`.
3. Instale e execute:

   ```bash
   python -m venv .venv
   source .venv/bin/activate       # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python scripts/auth_youtube.py
   ```

4. Na página Google, autentique-se com a conta que gere o canal novo e autorize YouTube. O script consulta o canal devolvido pela API e mostra o nome e o ID. Confirme que é o canal de receitas antes de copiar qualquer segredo.
5. Copie o texto completo de `token-recipes.json` para o secret do **novo** repositório. Não envie `token-recipes.json` nem `client_secret.json` para o GitHub.
6. Copie o ID mostrado para a variável `EXPECTED_YOUTUBE_CHANNEL_ID` no mesmo repositório.

Se a API indicar mais de um canal, o script pára. Não active publicação até conseguir um token que identifique só o canal certo. Para uma primeira prova, em **Actions → workflow → Run workflow**, deixe `upload` desligado: o vídeo aparece como artefacto de pré-visualização. Depois de o rever e confirmar o canal, a agenda publica automaticamente.

## Teste local sem publicar

Instale FFmpeg e execute:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m recipe_shorts --force
```

O preview e o JSON de proveniência ficam em `output/`. Por omissão, `UPLOAD_ENABLED=false`; a execução local nunca envia vídeos sem `--publish` ou configuração explícita.

## Configuração

O workflow usa os valores abaixo. Para mudar horários ou coleções, edite apenas `.github/workflows/publish.yml` no novo repositório.

| Variável | Valor padrão | O que controla |
|---|---|---|
| `TIMEZONE` | `Europe/Lisbon` | Fuso horário dos horários de publicação |
| `PUBLISH_HOURS` | `8,11,14,17,20,22` | Seis horas locais por dia |
| `RECIPE_COLLECTIONS` | `portugal,brazil` | Coleções a importar e selecionar |
| `TTS_VOICE` | `pt-PT-RaquelNeural` | Voz de texto para fala |
| `YOUTUBE_PRIVACY_STATUS` | `public` | Estado dos vídeos agendados |

## Limites e operação

- A consulta procura imagens de ingredientes individualmente e uma fotografia própria para o prato final. Com `PEXELS_API_KEY`, consulta também o Pexels; sem a chave, usa o Wikimedia Commons. Do Commons só aceita domínio público, CC0 ou CC BY/CC BY-SA e guarda o crédito e a página de origem. As fotos são descarregadas e verificadas antes da renderização; quando não existe uma foto adequada, o vídeo indica-o claramente.
- Antes de guardar ou enviar o ficheiro, o workflow valida com `ffprobe` que o vídeo está vertical e tem menos de 60 segundos. O YouTube classifica automaticamente os vídeos quadrados ou verticais até três minutos como Shorts; a API de upload não tem um campo para definir manualmente essa classificação. O título conserva `#Shorts` mesmo quando o nome da receita é longo.
- Os campos da receita são traduzidos para português antes de preparar o guião, com falha segura se o serviço de tradução estiver indisponível. A referência bibliográfica da fonte fica no idioma original para preservar a identificação da publicação.
- A narração usa Edge TTS online e precisa de rede. Uma indisponibilidade interrompe a execução, sem publicar o vídeo incompleto.
- É necessário ter a API do YouTube ativa e consentimento OAuth válido. Uma aplicação externa em estado **Testing** emite refresh tokens que expiram após sete dias; usa **Production** para a automação duradoura. As credenciais ficam nos GitHub Secrets/Variables; não são colocadas nos ficheiros de código.
- A publicação automática pode ser limitada pelo estado de verificação do projeto Google/API ou pelo estado da conta/canal. O artefacto do workflow permite rever a renderização antes de ativar a publicação pública.
- Se quiser usar outras coleções, altere `RECIPE_COLLECTIONS` para os slugs disponíveis no índice do arquivo. O gerador mantém o filtro de licença e a validação de estrutura.

## Estrutura

```text
.github/workflows/publish.yml   agenda e publicação, isoladas do CS2
src/recipe_shorts/library.py    sincronização, seleção e histórico sem repetição
src/recipe_shorts/content.py    guião e metadados com fonte
src/recipe_shorts/media.py      voz, grafismo/imagem e renderização 9:16
src/recipe_shorts/youtube.py    OAuth, verificação de canal e upload
scripts/auth_youtube.py         autorização OAuth inicial do canal de receitas
tests/                          testes de parser e conteúdo
```
