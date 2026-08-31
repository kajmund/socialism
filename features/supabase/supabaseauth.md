# Spec: Supabase-auth med magic link, backend-enforcement, admin-användarhantering

Bakgrund: idag finns ingen auth alls på backend — `main.py` har inga auth-dependencies, alla
endpoints är öppna. Frontend har en helt kosmetisk statisk inloggning (`lib/auth.ts`,
tre hårdkodade konton med lösenorden `admin`/`user`/`bolag`) som bara styr vad GUI:t visar,
inte vad API:et tillåter. `@supabase/supabase-js` finns redan som frontend-dependency men
används inte. Supabase-projektet finns redan uppsatt (env-nycklar tillhandahålls separat, inte
del av denna spec).

Beslutad scope: magic link (ingen lösenordshantering), full backend-enforcement (varje endpoint
nekar cross-kund-access, inte bara GUI-kosmetik), plus ett admin-GUI för användarhantering med
en **Bjud in**-knapp, nått via en länk i huvudmenyn.

De statiska testkontona (`admin`/`admin` osv) ska bort helt i sista fasen — de är en verklig
säkerhetslucka om de blir kvar parallellt med riktig auth.

Bygg i fem faser, i den här ordningen, en PR per fas:

---

## Fas A — Backend: verifiera Supabase-token, `UserAccount`-tabell, auth-dependency

### A.1 Ny tabell: `UserAccount`

I `database/models.py`. Detta är källan till roll+kund-koppling — Supabase-token bevisar bara
*identitet* (ett giltigt, verifierat `user_id`), inte vad användaren får göra. Det avgörs här,
i vår egen databas, precis som `Kund.available_modules` redan är källan för moduler.

```python
class UserAccount(Base):
    """Roll + kund-koppling för en Supabase-autentiserad användare."""

    __tablename__ = "user_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Supabase auth.users.id (uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "admin" | "user" | "bolag"
    kund_id: Mapped[int | None] = mapped_column(
        ForeignKey("kunder.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`kund_id` nullable — en admin är inte nödvändigtvis knuten till en specifik kund (motsvarar
dagens `kundSlug: null` för admin, som idag betyder "union av alla kunders moduler").

### A.2 Config

`config.py`: lägg till `supabase_url: str`, `supabase_jwt_secret: str` (för att verifiera
tokens signatur/utgångstid — HS256 delad hemlighet, Supabase's standardläge om inget annat
konfigurerats), `supabase_service_role_key: str` (endast backend, används i Fas C för att
bjuda in användare — **skickas aldrig till frontend, bara `SUPABASE_ANON_KEY` gör det**).

Ny dependency: `pyjwt` i `pyproject.toml`.

### A.3 Auth-dependency

Ny fil `backend/app/auth/dependencies.py`:

```python
async def get_current_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> UserAccount:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid_token")
    user_id = payload.get("sub")
    account = await session.get(UserAccount, user_id)
    if account is None:
        # Giltig Supabase-token men ingen rad i UserAccount — inte inbjuden av admin, neka.
        raise HTTPException(403, "not_provisioned")
    account.last_seen_at = utcnow()
    await session.commit()
    return account


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if user.role != "admin":
        raise HTTPException(403, "admin_required")
    return user
```

Ingen self-signup-väg — en verifierad Supabase-token utan motsvarande `UserAccount`-rad ger
403, inte automatisk provisionering. Provisionering sker bara via admins Bjud in-knapp (Fas C).

### A.4 Acceptanskriterium

- Ett endpoint-test som anropar ett skyddat API utan `Authorization`-header ger 401.
- Ett test med en giltig Supabase-token men utan `UserAccount`-rad ger 403.
- Ingen router är kopplad in i `main.py` ännu — den här fasen bygger bara mekaniken.

---

## Fas B — Backend: full enforcement per endpoint

Det här är den stora, riskfyllda fasen — gå igenom varje router systematiskt, inte punktvis.

### B.1 Mönster

Varje route som rör kund-scopad data (kampanjer, rapporter, jobb, personas, populations,
runs, messages) får `Depends(get_current_user)` och filtrerar/nekar på `user.kund_id`:

- `role == "admin"`: ingen filtrering, ser allt.
- `role in ("user", "bolag")`: query filtreras på `customer_id == user.kund_id`, ELLER om
  resursen redan hämtats via id: `if row.customer_id != user.kund_id: raise HTTPException(403)`.

Rutt-lista att gå igenom (läs varje fil, avgör vad som är kund-scopat innan ändring, gissa
inte): `api/dd.py` (kampanjer), `api/reports.py`, `api/jobs.py`, `api/personas.py`,
`api/populations.py`, `api/messages.py` (om separat router finns), `api/spindoctor.py`,
`api/panel.py`. Rena admin-ytor (`api/kunder.py` PATCH, `api/panel_catalog.py`,
`api/configurations.py`, `api/catalog.py`, `api/label_vocabularies.py`, `api/anchor_sets.py`)
får `Depends(require_admin)` rakt av — de har ingen kund-dimension att filtrera på, de är
plattformskonfiguration.

`api/health.py` förblir helt öppen (uptime-koll).

### B.2 Kända fallgropar (kolla explicit, inte bara i förbifarten)

- WebSocket-routern (`api/ws.py`) — token skickas inte som header, måste läsas ur
  query-param eller första meddelandet vid connect. Läs hur `ws.py` faktiskt är byggd innan
  du bestämmer var token-koll ska sitta.
- `Job`/`Report`-tabellerna har redan `customer_id` — filtrera på den, inte på att gissa via
  relaterad kampanj.
- DD:s `PanelSession`/`DdCandidateRun` saknar egen `customer_id` — de hänger av `DdCampaign`,
  så access-kollen måste gå via kampanjens `customer_id`, inte på sessionen direkt.

### B.3 Acceptanskriterium

- En `user`-inloggad kund kan inte hämta en annan kunds kampanj/rapport/jobb via id, ens om
  de gissar rätt id — 403, inte tyst tomt svar.
- Alla befintliga tester uppdaterade med giltig `Authorization`-header (fixture i
  `conftest.py`, en per roll: admin-token, user-token knuten till devbrains, bolag-token
  knuten till bolag-demo).
- `main.py` startar inte om `SUPABASE_JWT_SECRET` saknas (samma "fail loud"-mönster som
  `DEEPSEEK_API_KEY`).

---

## Fas C — Backend: admin-användarhantering (Bjud in-knapp)

### C.1 Ny router `api/users.py`, hela routern `Depends(require_admin)`

- `GET /users` — lista `UserAccount`, joinat med `Kund.name` för visning.
- `POST /users/invite` — body `{email, role, kund_id}`. Anropar Supabase Admin API
  (`POST {SUPABASE_URL}/auth/v1/admin/invite` eller motsvarande i deras Python-klient om den
  läggs till, annars ren `httpx`-POST med `service_role_key` i headern — **kolla Supabase's
  faktiska admin-invite-endpoint-kontrakt innan implementation, gissa inte URL/payload-form**).
  Skapar `UserAccount`-raden i vår DB med det `user_id` Supabase returnerar.
- `PATCH /users/{id}` — ändra `role`/`kund_id` för en befintlig användare (t.ex. flytta någon
  mellan roller, eller koppla om till en annan kund).
- Inget `DELETE` i denna fas — inaktivera är inte en del av scope, lägg till senare om det
  visar sig behövas.

### C.2 Acceptanskriterium

- Admin kan bjuda in `olle@norrkoping.se` med `role="user"`, `kund_id` = devbrains (eller ny
  kund om ni vill separera Olle från interna Devbrains-konton — avgör vid implementation,
  inte i denna spec, låg risk att ändra senare).
- Icke-admin som anropar `/users/*` får 403.

---

## Fas D — Frontend: Supabase-klient + magic-link-inloggning

### D.1 Supabase-klient

Ny fil `frontend/src/lib/supabaseClient.ts`:
```ts
import { createClient } from "@supabase/supabase-js"
export const supabase = createClient(env.supabaseUrl, env.supabaseAnonKey)
```
Lägg `supabaseUrl`/`supabaseAnonKey` i `lib/env.ts` (läs filen först — okänt om den redan har
ett mönster för publika env-variabler att följa).

### D.2 `lib/auth.ts` — byt adapter-kontrakt

Magic link är tvåstegs (begär länk → användaren klickar externt → sessionen dyker upp i
appen), så `AuthAdapter`-typen ändras, inte bara implementationen:

```ts
export type AuthAdapter = {
  requestMagicLink(email: string): Promise<void>
  signOut(): Promise<void>
  getSession(): Promise<AuthSession | null>
  getAccessToken(): Promise<string | null>
  onSessionChange(cb: (session: AuthSession | null) => void): () => void
}
```

`getSession`/`onSessionChange` hämtar `supabase.auth.getSession()`/`onAuthStateChange` och
mappar Supabase-sessionen mot vårt `AuthSession`/`AuthUser` — men `role`/`kundSlug`/`modules`
finns inte i Supabase-sessionen, de hämtas separat.

### D.3 Ny backend-endpoint `GET /me`

Enklaste sättet att undvika att frontend gissar kund-koppling (som `resolveModules()` gör
idag via `listKunder()` + slug-matchning — det var en for-demo-genväg, ersätt den nu):
`GET /me` (auth-krävd) returnerar `{role, kund_id, kund_slug, available_modules}` direkt från
`UserAccount`+`Kund`. `AuthProvider.tsx` anropar den en gång efter att Supabase-sessionen
etablerats, istället för `resolveModules()`s nuvarande listKunder-logik. Radera
`kundSlugForUsername`/`STATIC_ACCOUNTS`-relaterad kod i samma veva.

### D.4 Login-sida

Byt lösenordsformuläret mot ett e-postfält + "Skicka inloggningslänk"-knapp, och ett
"Kolla din inkorg"-tillstånd efter att länken skickats. Ingen ny design behövs, återanvänd
befintlig sidstruktur.

### D.5 Acceptanskriterium

- Inloggning fungerar end-to-end mot det riktiga Supabase-projektet med en riktig
  e-postadress.
- De statiska testkontona (`admin`/`admin` etc) är helt borttagna ur koden.

---

## Fas E — Frontend: Användarhantering-GUI

### E.1 Ny sida `frontend/src/pages/AnvandarePage.tsx`

Admin-gated (samma mönster som `PanelCatalogPage`/`KunderPage`). Tabell: e-post, roll, kund,
inbjuden-datum. **Bjud in**-knapp öppnar ett formulär (e-post, roll-väljare, kund-väljare —
kund-väljaren döljs/inaktiveras om roll är "admin", eftersom admin inte är kund-bunden).

### E.2 Nav-länk i huvudmenyn

Lägg till i `AdminShell.tsx`s `DEFAULT_NAV_ITEMS` (eller motsvarande admin-only-lista, samma
mönster som `nav.tools` redan filtreras på `isAdmin`): en post `nav.users` → `/tools/anvandare`,
synlig bara för admin.

### E.3 Acceptanskriterium

- Admin loggar in, ser länken i huvudmenyn, kan bjuda in en ny användare och se den dyka upp
  i listan.

---

## PR-ordning

Fem separata PR:er, i ordningen A → B → C → D → E. **Fas B är den som kan gå sönder tyst** —
den rör om i varenda skyddad endpoint. Kör den ensam, inte ihopblandad med något annat arbete
i samma PR, och vänta på granskning innan C påbörjas.