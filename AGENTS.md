# Finance-God Agent Instructions

## Frontend source of truth

Before designing, changing, or reviewing any Finance-God frontend, read:

1. `docs/page-design/01_前端统一设计规范.md`
2. `docs/page-design/02_前后端职责与数据合同.md`
3. `docs/page-design/templates/前端设计验收模板.md`
4. The page-specific specification in `docs/page-design/pages/` for every
   affected route.

The frontend design requirements are normative. If an older page document conflicts
with them, the frontend design requirements win and the older document must be
updated in the same change.

## Required workflow

Every frontend task must produce a short design brief before implementation:

Use `docs/page-design/templates/前端设计简报模板.md`.

- user and operating context;
- page task and primary object;
- information hierarchy and workspace regions;
- real-data sources, frequency, freshness, and failure states;
- primary action and the conditions that enable it;
- affected routes and desktop widths.

After implementation, copy the acceptance template and report every item as
`通过`, `失败`, or `不适用`, with evidence. Do not claim completion while a required
item is unverified.

## Product constraints

- Finance-God is a desktop trading product for both capable retail users and
  professional traders.
- Primary canvas: 1440 px. Minimum supported width: 1024 px. Below 1024 px, show
  an explicit desktop-width notice. Do not create a mobile layout.
- Use a warm editorial financial-terminal workspace: warm beige paper surfaces,
  deep ink typography, fine rules, dense tabular information and restrained
  interaction. Financial newspapers may inform material, proportion and
  hierarchy; trading terminals may inform density and operational clarity.
  Do not copy third-party brand assets or exact compositions.
- Global navigation is a compact top bar. Workspace tabs sit below it when a page
  has multiple tools.
- Surfaces use warm beige and light paper tones with deep brown-black ink.
  Selection and primary actions use ink weight, underlines and rules rather than
  blue. Red/green are reserved for loss/sell/risk and gain/buy/pass.
- Do not build dashboard card mosaics. Use workspace regions, dividers, tables,
  tabs, toolbars, charts, and inspectors.
- UI copy must describe function. Ban slogans, metaphors, design commentary, and
  vague phrases such as “事实流”, “智能中枢”, “全景洞察”, or “闭环赋能” unless the
  term is a defined domain object.
- Supporting text exists only to explain scope, operation, freshness, or decision
  value. Remove it if it does none of these jobs.
- PandaData is the market-data source. The UI may poll at up to one-second
  intervals, but must display the upstream timestamp and actual data frequency.
- Market data is real. Account, position, order, fill, and execution data remain
  explicitly labeled simulation data.
- AI is contextual and persistent on every desktop route. Use one shared right-side
  sidebar that follows the current page/object, is expanded by default at wide
  desktop widths, can collapse to a visible rail, and persists the user's choice.
  It must not become a modal drawer or floating chatbot bubble.
- Relevant workspaces support panel show/hide, resizing, tab ordering, reset, and
  browser persistence.

## Engineering constraints

- Production frontend baseline: Vue 3, TypeScript and Vite. Use Vue Router for
  client-side routing and Pinia for shared client state; keep route views,
  charts, polling, workspace manipulation, forms and dialogs in explicit
  components, composables or stores with clear ownership.
- Stable page data is loaded through typed frontend services. Vite's `/api`
  proxy is a local-development boundary only; production deployments must route
  the same-origin API path to the backend without exposing PandaData credentials.
- Build a Finance-God-owned component layer and design tokens. Do not copy OKX
  internal `okui-` component names, CSS, brand assets, or implementation details.
- Use `lightweight-charts` for production trading charts unless a page-specific
  technical review approves another chart engine.
- The browser never receives PandaData credentials.
- Market-data access goes through the backend adapter and a normalized API
  contract.
- Use one shared polling controller and cache; do not let individual widgets poll
  PandaData independently.
- Stop polling when the document is hidden and resume with an immediate refresh.
- A request failure must produce a visible stale/error state. Never replace failed
  real data with fabricated values.
- Keep simulated business data and real market data in separate state objects and
  label them in the UI.
- Preserve keyboard access, visible focus, semantic tables, dialogs, drawers, and
  reduced-motion behavior.
