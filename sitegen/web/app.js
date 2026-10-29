const view = document.getElementById('view');
let config = null;
let models = null;

const LABELS = {
  brand: 'Бренд', legal_name: 'Юридическое название', founding_year: 'Год основания', employee_count: 'Сотрудников',
  tagline: 'Предложение компании', value_proposition: 'Ценность для клиента', advantages: 'Преимущества',
  history: 'История', specialization: 'Специализация', audience: 'Целевая аудитория',
  client_problem: 'Проблема клиента', product: 'Продукт', faq: 'Вопросы и ответы', people: 'Команда',
  name: 'Имя / название', role: 'Должность', level: 'Уровень', bio: 'Биография', summary: 'Описание',
  inputs: 'Входные данные', process: 'Как работает', outputs: 'Результат', limitations: 'Ограничения',
  question: 'Вопрос', answer: 'Ответ', country: 'Страна', direction: 'Направление', service_type: 'Тип сервиса',
  scale: 'Масштаб', language: 'Язык карточки', contacts: 'Контакты', city: 'Город', postal_code: 'Индекс',
  street: 'Улица', phone: 'Телефон', email: 'Почта', sections: 'Разделы',
  scenarios: 'Сценарии использования', situation: 'Ситуация', how_it_helps: 'Как помогает продукт',
};
const READONLY = ['level', 'country', 'direction', 'service_type', 'scale', 'language'];
const STATUS = { draft: 'черновик', facts_approved: 'факты утверждены', approved: 'утверждена' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (v) => '$' + Number(v).toFixed(4);
const when = (s) => new Date(s).toLocaleString('ru-RU');

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!res.ok) {
    let msg = res.statusText;
    try { const d = await res.json(); msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail); } catch (e) { /* не json */ }
    throw new Error(msg);
  }
  return res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ждём задачу и показываем этап
//расходы: база с сервера + что уже потратила задача
const spendBase = { total: 0, company: null };

function showSpend(extra = 0) {
  const total = document.getElementById('spendTotal');
  if (total) total.innerHTML = `<span class="muted">потрачено</span> ${money(spendBase.total + extra)}`;
  const one = document.getElementById('spendCompany');
  if (one && spendBase.company != null) one.textContent = money(spendBase.company + extra);
}

async function refreshSpend() {
  try {
    spendBase.total = (await api('/api/spend')).total;
  } catch (e) { /* без счётчика тоже живём */ }
  showSpend();
}

async function waitJob(jobId, box, onStage = null) {
  const started = Date.now();
  let last = null;
  for (;;) {
    const j = await api('/api/jobs/' + jobId);
    const cost = j.cost_known ? `${money(j.cost)} из ${money(j.limit)}` : 'стоимость неизвестна';
    const secs = Math.round((Date.now() - started) / 1000);
    box.innerHTML = `<div class="progress"><span class="spinner"></span><b>${esc(j.stage)}</b>
      <br><span class="muted">Идёт ${secs} с, потрачено ${cost}</span></div>`;
    showSpend(j.cost);
    if (onStage && j.stage !== last) onStage(j.stage);
    last = j.stage;
    if (j.status !== 'running') {
      // при ошибке деньги тоже могли уйти
      await refreshSpend();
    }
    if (j.status === 'done') return j;
    if (j.status === 'error') throw new Error(j.error);
    await sleep(1200);
  }
}

function options(list, withRandom) {
  const head = withRandom ? '<option value="random">Случайно из каталога</option>' : '';
  return head + list.map((o) => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join('');
}

//помним последний выбор
function remember(name, value) {
  try {
    if (value === undefined) return localStorage.getItem('pick:' + name);
    localStorage.setItem('pick:' + name, String(value));
  } catch (e) { /* приватное окно, без памяти */ }
  return null;
}

async function ensureModels() {
  if (models) return;
  try {
    models = await api('/api/models');
  } catch (e) {
    models = { presets: [{ id: config.default_model, label: config.default_model, note: '', prompt_per_m: null, completion_per_m: null }], others: [] };
  }
}

// компания целиком ~15к токенов туда и столько же обратно
const COMPANY_TOKENS = 15000;

//text для текстов, image для фото
const KINDS = {
  text: { list: () => models.presets, others: () => models.others, memory: 'model', fallback: () => config.default_model },
  image: { list: () => models.image_presets, others: () => models.image_others, memory: 'imageModel', fallback: () => config.default_image_model },
};

function priceText(m) {
  if (m.per_image != null) return `примерно $${m.per_image.toFixed(3)} за фото`;
  if (m.prompt_per_m == null) return '';
  if (m.prompt_per_m === 0 && m.completion_per_m === 0) return 'бесплатно';
  const one = ((m.prompt_per_m + m.completion_per_m) * COMPANY_TOKENS) / 1e6;
  return `примерно $${one < 0.01 ? one.toFixed(3) : one.toFixed(2)} за компанию`;
}

function modelNote(id, kind = 'text') {
  const m = KINDS[kind].list().find((x) => x.id === id);
  if (!m) return 'Своя модель: цену и лимит смотрите на openrouter.ai/models.';
  let price;
  if (kind === 'image') {
    price = m.per_image == null ? 'цена неизвестна, OpenRouter не ответил' : `Примерно $${m.per_image.toFixed(3)} за одно фото`;
  } else {
    price = m.prompt_per_m == null ? 'цена неизвестна, OpenRouter не ответил'
      : `За 1 млн токенов: запрос $${m.prompt_per_m.toFixed(2)}, ответ $${m.completion_per_m.toFixed(2)}`;
  }
  return [m.note, price].filter(Boolean).join('. ');
}

function modelPicker(id, kind = 'text') {
  const k = KINDS[kind];
  const saved = remember(k.memory) || k.fallback();
  const known = k.list().some((m) => m.id === saved);
  const opts = k.list().map((m) => {
    const price = priceText(m);
    return `<option value="${esc(m.id)}"${m.id === saved ? ' selected' : ''}>${esc(m.label)}${price ? ', ' + price : ''}</option>`;
  }).join('');
  const others = k.others().map((m) => `<option value="${esc(m)}">`).join('');
  return `<label>${kind === 'image' ? 'Модель изображений' : 'Модель'}
      <select id="${id}" data-picker="model" data-kind="${kind}">${opts}<option value="__custom"${known ? '' : ' selected'}>Другая модель...</option></select>
      <small class="muted" id="${id}Note">${esc(known ? modelNote(saved, kind) : modelNote('', kind))}</small></label>
    <label id="${id}Custom"${known ? ' hidden' : ''}>Модель из каталога OpenRouter
      <input id="${id}Name" list="${id}List" placeholder="провайдер/модель" value="${known ? '' : esc(saved)}">
      <datalist id="${id}List">${others}</datalist></label>`;
}

function readModel(id) {
  const sel = document.getElementById(id);
  const value = sel.value === '__custom' ? document.getElementById(id + 'Name').value.trim() : sel.value;
  if (!value) throw new Error('Укажите модель');
  remember(KINDS[sel.dataset.kind || 'text'].memory, value);
  return value;
}

function limitPicker(id, memory = 'limit', fallback = null) {
  const saved = Number(remember(memory)) || fallback || config.max_cost_usd;
  const known = config.cost_presets.includes(saved);
  const opts = config.cost_presets.map((v) => `<option value="${v}"${v === saved ? ' selected' : ''}>$${v.toFixed(2)}</option>`).join('');
  return `<label>Лимит расходов на операцию
      <select id="${id}" data-picker="limit" data-memory="${memory}">${opts}<option value="__custom"${known ? '' : ' selected'}>Свой...</option></select>
      <small class="muted">Дороже лимита запрос не уйдёт, остаток не сгорает</small></label>
    <label id="${id}Custom"${known ? ' hidden' : ''}>Свой лимит, $
      <input id="${id}Value" type="number" min="0.01" max="${config.max_cost_cap_usd}" step="0.01" value="${known ? '' : saved}"></label>`;
}

function readLimit(id) {
  const sel = document.getElementById(id);
  const value = Number(sel.value === '__custom' ? document.getElementById(id + 'Value').value : sel.value);
  if (!(value > 0 && value <= config.max_cost_cap_usd)) {
    throw new Error(`Лимит должен быть больше $0 и не выше $${config.max_cost_cap_usd.toFixed(2)}`);
  }
  remember(sel.dataset.memory || 'limit', value);
  return value;
}

// при выборе «свой вариант» показываем поле и подсказку
document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.picker) return;
  const custom = document.getElementById(el.id + 'Custom');
  if (custom) custom.hidden = el.value !== '__custom';
  const note = document.getElementById(el.id + 'Note');
  if (note) note.textContent = modelNote(el.value === '__custom' ? '' : el.value, el.dataset.kind || 'text');
});

// ---------- список компаний ----------

// small -> «небольшая», без скобок с числом сотрудников, в таблице и так тесно
const scaleLabel = (key) => (config.catalog.scales.find((s) => s.key === key) || { label: key }).label.split(' (')[0];

async function showList() {
  const items = await api('/api/companies');
  if (!items.length) {
    view.innerHTML = '<h2>Компании</h2><p class="muted">Пока пусто. Создайте первую на вкладке «Новая компания».</p>';
    return;
  }
  const rows = items.map((c) => `<tr>
    <td class="code">${c.code}</td>
    <td><a href="#/company/${c.id}">${esc(c.brand)}</a><br><span class="muted">${esc(c.data.legal_name)}</span></td>
    <td>${esc(c.data.contacts.city)}</td>
    <td>${esc(scaleLabel(c.data.scale))}</td>
    <td><span class="badge ${c.status}">${STATUS[c.status] || c.status}</span></td>
    <td>${money(c.cost)}</td>
    <td>${when(c.created_at)}</td>
    <td><button class="link danger" data-del-company="${c.id}" data-name="${esc(c.brand)}">Удалить</button></td></tr>`).join('');
  view.innerHTML = `<h2>Компании</h2><table>
    <tr><th>ID</th><th>Компания</th><th>Город</th><th>Масштаб</th><th>Статус</th><th>Расход</th><th>Создана</th><th></th></tr>${rows}</table>`;
}

// ---------- новая компания ----------

async function showNew() {
  await ensureModels();
  const cat = config.catalog;
  view.innerHTML = `<h2>Новая компания</h2><div class="panel"><form id="genForm">
    <div class="row">
      <label>Название бренда <input name="brand" maxlength="60" placeholder="пусто: придумает модель"></label>
      <label>Страна <select name="country">${options(cat.countries, true)}</select></label>
      <label>Направление <select name="direction">${options(cat.directions, true)}</select></label>
      <label>Тип B2B-сервиса <select name="service_type">${options(cat.service_types, true)}</select></label>
      <label>Масштаб <select name="scale">${options(cat.scales, true)}</select></label>
      <label>Язык карточки <select name="language">${options(cat.languages, false)}</select></label>
    </div>
    <div class="row">${modelPicker('genModel')}${limitPicker('genLimit')}</div>
    <fieldset><legend>Разделы карточки</legend>
      <p class="muted">Сначала создаются общие факты: оператор, контакты, продукт, сценарии и FAQ. Отмеченные разделы создаются после того, как вы утвердите факты, каждый отдельным запросом.</p>
      ${config.aspects.map((a, i) => `<label class="check"><input type="checkbox" name="aspects" value="${esc(a.key)}" checked> ${i + 1}. ${esc(a.title)}</label>`).join('')}
    </fieldset>
    <button type="submit">Сгенерировать</button>
  </form><div id="genBox"></div></div>`;

  document.getElementById('genForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const box = document.getElementById('genBox');
    const form = new FormData(e.target);
    const body = Object.fromEntries(form);
    body.aspects = form.getAll('aspects');
    const btn = e.target.querySelector('button[type=submit]');
    btn.disabled = true;
    try {
      body.model = readModel('genModel');
      body.max_cost = readLimit('genLimit');
      const job = await api('/api/companies/generate', { method: 'POST', body: JSON.stringify(body) });
      const done = await waitJob(job.id, box);
      if (done.warning) {
        box.innerHTML = `<div class="error">${esc(done.warning)}</div>
          <a class="btn" href="#/company/${done.result_id}">Открыть компанию</a>`;
        return;
      }
      location.hash = '#/company/' + done.result_id;
    } catch (err) {
      box.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      btn.disabled = false;
    }
  });
}

// ---------- карточка компании ----------

// вкладки редактора, что ни в одну не попало, уходит в «Компанию»
const CARD_TABS = [
  ['company', 'Компания', ['brand', 'legal_name', 'founding_year', 'employee_count', 'country', 'direction', 'service_type', 'scale', 'language']],
  ['offer', 'Предложение', ['tagline', 'value_proposition', 'advantages', 'audience', 'client_problem']],
  ['story', 'История', ['history', 'specialization']],
  ['team', 'Команда', ['people']],
  ['contacts', 'Контакты', ['contacts']],
  ['product', 'Продукт', ['product']],
  ['faq', 'FAQ', ['faq']],
];

function cardTabs(data) {
  const tabs = CARD_TABS.map(([key, title, fields]) => ({ key, title, paths: fields.filter((f) => f in data).map((f) => [f]) }));
  const known = new Set(CARD_TABS.flatMap((t) => t[2]).concat('sections'));
  Object.keys(data).filter((k) => !known.has(k)).forEach((k) => tabs[0].paths.push([k]));
  // у каждого раздела своя вкладка, короткое имя берём из подписей
  Object.keys(data.sections || {}).forEach((key) => {
    tabs.push({ key: 'sec-' + key, title: config.labels[key] || key, paths: [['sections', key]] });
  });
  return tabs.filter((t) => t.paths.length);
}

function renderPath(data, path) {
  let value = data;
  path.forEach((k) => { value = value[k]; });
  // объект во вкладке и так один, рамка с заголовком вокруг него лишняя
  if (value && typeof value === 'object' && !Array.isArray(value)) return objectFields(value, path);
  return fieldHtml(value, path);
}

function tabHtml(data, tab) {
  if (tab.paths.length === 1) return renderPath(data, tab.paths[0]);
  // несколько полей верхнего уровня, собираем их в один объект, чтоб легли в сетку
  return objectFields(Object.fromEntries(tab.paths.map(([k]) => [k, data[k]])), []);
}

const isShort = (v, k) => typeof v === 'number' || (typeof v === 'string' && (v.length <= 80 || READONLY.includes(k)));

function objectFields(obj, path) {
  // короткие поля подряд кладём в сетку, а не по одному на всю ширину
  let html = '';
  let short = [];
  const flush = () => {
    if (short.length) html += `<div class="grid">${short.join('')}</div>`;
    short = [];
  };
  Object.entries(obj).forEach(([k, v]) => {
    const field = fieldHtml(v, [...path, k]);
    if (isShort(v, k)) short.push(field);
    else { flush(); html += field; }
  });
  flush();
  return html;
}

function itemTitle(item, label, i) {
  const title = item.name || item.title || item.question || item.author_name || item.category || item.area || item.key || `${label} ${i + 1}`;
  return String(title).length > 60 ? String(title).slice(0, 57) + '...' : String(title);
}

const rowsFor = (text, width = 70) => Math.min(12, Math.max(2, Math.ceil(String(text).length / width) + 1));

function autosize(el) {
  if (!el.offsetParent) return;
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 2 + 'px';
}

function fieldHtml(value, path) {
  const key = path[path.length - 1];
  const label = config.labels[key] || LABELS[key] || key;
  const p = esc(JSON.stringify(path));
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v === 'string')) {
      return `<label>${label} <small>по одному пункту в строке</small>
        <textarea data-path="${p}" data-kind="lines" rows="${value.length + 1}">${esc(value.join('\n'))}</textarea></label>`;
    }
    // люди, вопросы, сценарии карточками в две колонки, подписаны именем или вопросом
    const items = value.map((v, i) => `<fieldset class="item"><legend>${esc(itemTitle(v, label, i))}</legend>${objectFields(v, [...path, i])}</fieldset>`);
    return `<div class="items-head">${label} <span class="badge">${value.length}</span></div><div class="items">${items.join('')}</div>`;
  }
  if (value && typeof value === 'object') {
    return `<fieldset><legend>${label}</legend>${objectFields(value, path)}</fieldset>`;
  }
  const ro = READONLY.includes(key) ? ' readonly' : '';
  if (typeof value === 'number') {
    return `<label>${label}<input type="number" data-path="${p}" data-kind="num" value="${value}"${ro}></label>`;
  }
  if (String(value).length > 80) {
    return `<label>${label}<textarea data-path="${p}" data-kind="str" rows="${rowsFor(value)}">${esc(value)}</textarea></label>`;
  }
  return `<label>${label}<input data-path="${p}" data-kind="str" value="${esc(value)}"${ro}></label>`;
}

function collect(root, original) {
  const data = structuredClone(original);
  root.querySelectorAll('[data-path]').forEach((el) => {
    const path = JSON.parse(el.dataset.path);
    let v = el.value;
    if (el.dataset.kind === 'num') v = Number(v);
    if (el.dataset.kind === 'lines') v = v.split('\n').map((s) => s.trim()).filter(Boolean);
    let node = data;
    path.slice(0, -1).forEach((k) => { node = node[k]; });
    node[path[path.length - 1]] = v;
  });
  return data;
}

function issuesBox(issues) {
  if (!issues || !issues.length) return '';
  const items = issues.map((i) => `<li>${esc(i)}</li>`).join('');
  return `<div class="error"><b>Проверка кодом нашла проблемы, их нужно исправить в карточке:</b><ul>${items}</ul></div>`;
}

function stepHead(n, title, done) {
  return `<h3 class="step"><span class="badge ${done ? 'ok' : ''}">${n}</span> ${title}</h3>`;
}

function factsStep(company) {
  const st = company.state;
  const body = st.facts_approved
    ? '<p><span class="badge ok">утверждены</span> Разделы строятся только на этой версии фактов. Правка фактов снимет утверждение.</p>'
    : `<p class="muted">Общие факты: юрлицо, история, команда, контакты, продукт, сценарии и FAQ. Проверьте их, при необходимости поправьте ниже и утвердите.</p>
       <button id="approveFacts">Утвердить факты</button>`;
  return `<div class="panel">${stepHead(1, 'Общие факты', st.facts_approved)}${body}<div id="factsBox"></div></div>`;
}

function aspectsStep(company) {
  const st = company.state;
  const have = Object.keys(company.data.sections || {});
  const rows = config.aspects.map((a, i) => {
    const has = have.includes(a.key);
    const blocked = !st.facts_approved || a.requires.some((r) => !have.includes(r));
    let mark = has ? '<span class="badge ok">есть</span>' : '<span class="badge">нет</span>';
    if (st.stale_sections.includes(a.key)) mark += ' <span class="badge warn">по старым фактам</span>';
    const gen = `<button class="secondary" data-aspect="${esc(a.key)}" data-action="generate"${blocked ? ' disabled' : ''}>${has ? 'Создать заново' : 'Сгенерировать'}</button>`;
    const del = has ? `<button class="secondary" data-aspect="${esc(a.key)}" data-action="remove">Удалить</button>` : '';
    return `<tr data-row="${esc(a.key)}"><td>${i + 1}</td><td>${esc(a.title)}</td><td class="mark">${mark}</td><td>${gen} ${del}</td></tr>`;
  }).join('');
  //устаревшие пересоздаются той же кнопкой
  const planned = (st.planned || []).filter((k) => !have.includes(k) || st.stale_sections.includes(k));
  const bulk = planned.length
    ? `<button id="bulkSections"${st.facts_approved ? '' : ' disabled'}>Создать и обновить разделы (${planned.length})</button>`
    : '';
  const hint = st.facts_approved
    ? 'Каждый раздел видит все общие факты и уже готовые разделы. После создания разделов сразу идёт совместная проверка.'
    : 'Разделы станут доступны после утверждения фактов.';
  return `<div class="panel">${stepHead(2, 'Разделы', have.length && !st.stale_sections.length)}
    <p class="muted">${hint}</p>
    <table><tr><th>№</th><th>Раздел</th><th></th><th></th></tr>${rows}</table>
    <div class="actions">${bulk}</div><div id="sectionsBox"></div></div>`;
}

function reviewStep(company) {
  const st = company.state;
  const r = st.review;
  let status;
  if (!r) status = '<p><span class="badge">не проводилась</span></p>';
  else if (!st.review_current) status = '<p><span class="badge warn">устарела</span> Карточку изменили после проверки, её нужно провести заново.</p>';
  else if (r.ok) status = `<p><span class="badge ok">пройдена</span> Противоречий не найдено. <span class="muted">${esc(r.model)}, ${when(r.checked_at)}</span></p>`;
  else {
    const items = r.contradictions.map((c) => `<li><b>${esc(c.where)}</b>: ${esc(c.problem)}${c.fix ? `<br><span class="muted">Как исправить: ${esc(c.fix)}</span>` : ''}</li>`).join('');
    status = `<div class="error"><b>Найдены противоречия (${r.contradictions.length}):</b><ul>${items}</ul></div>`;
  }
  const can = st.facts_approved && !company.issues.length;
  return `<div class="panel">${stepHead(3, 'Совместная проверка комплекта', st.review_current && r && r.ok)}
    <p class="muted">Модель читает всю карточку целиком и ищет расхождения в числах, сроках, именах и обещаниях между разделами. Проверка кодом идёт всегда и бесплатно.</p>
    ${status}
    <button id="runReview" class="secondary"${can ? '' : ' disabled'}>Проверить комплект</button><div id="reviewBox"></div></div>`;
}

function photosPanel(company) {
  const st = company.state;
  const people = company.data.people;
  const ready = st.photos.filter(Boolean).length;
  const cards = people.map((p, i) => {
    const img = st.photos[i]
      ? `<img src="/api/companies/${company.id}/photos/${i}?v=${encodeURIComponent(company.updated_at)}" alt="${esc(p.name)}">`
      : '<div class="no-photo">нет фото</div>';
    const redo = `<button class="link" data-photo="${i}"${st.facts_approved ? '' : ' disabled'}>${st.photos[i] ? 'Перегенерировать' : 'Сгенерировать'}</button>`;
    return `<li data-person="${esc(p.name)}">${img}<span>${esc(p.name)}</span><em class="state"></em>${redo}</li>`;
  }).join('');
  const missing = people.length - ready;
  const hint = st.facts_approved
    ? `Портреты вымышленных людей по имени и должности. Пока фото нет, на сайте стоит условный силуэт. На всю команду из ${people.length} человек лимита $0.10 может не хватить, лучше $0.50.`
    : 'Фото станут доступны после утверждения фактов: они делаются по утверждённой команде.';
  return `<div class="panel"><h3 class="step"><span class="badge ${missing ? '' : 'ok'}">фото</span> Фото команды, ${ready} из ${people.length}</h3>
    <p class="muted">${hint}</p>
    <ul class="photos">${cards}</ul>
    <div class="row">${modelPicker('photoModel', 'image')}${limitPicker('photoLimit', 'photoLimit', 0.5)}</div>
    <div class="actions">
      <button id="makePhotos"${st.facts_approved && missing ? '' : ' disabled'}>Сгенерировать недостающие (${missing})</button>
      <button id="redoPhotos" class="secondary"${st.facts_approved ? '' : ' disabled'}>Перегенерировать всех</button>
    </div><div id="photoBox"></div></div>`;
}

function approveStep(company) {
  const st = company.state;
  const ready = st.facts_approved && !company.issues.length && st.review_current && st.review && st.review.ok;
  const body = st.approved
    ? '<p><span class="badge approved">утверждена</span> Из карточки можно собирать сайт.</p>'
    : `<p class="muted">Нужны утверждённые факты, чистая проверка кодом и пройденная совместная проверка для текущей версии.</p>
       <button id="approve"${ready ? '' : ' disabled'}>Утвердить комплект</button>`;
  return `<div class="panel">${stepHead(4, 'Утверждение комплекта', st.approved)}${body}<div id="approveBox"></div></div>`;
}

function themeLabel(key) {
  const th = config.themes.find((x) => x.key === (key || 'classic'));
  return th ? th.label : key;
}

function sitesTable(sites, withBrand) {
  if (!sites.length) return '<p class="muted">Сайтов пока нет.</p>';
  const rows = sites.map((s) => {
    const checks = s.report.checks.map((c) => `<li class="${c.ok ? '' : 'fail'}">${c.ok ? 'ок' : 'ошибка'}: ${esc(c.name)}</li>`).join('');
    return `<tr>
      <td class="code">${s.code}</td>
      ${withBrand ? `<td><a href="#/company/${s.company_id}">${esc(s.brand)}</a></td>` : ''}
      <td>${s.language === 'ru' ? 'русский' : 'немецкий'}<br><span class="muted">${esc(themeLabel(s.style.theme))}, ${esc(s.style.scheme)}, ${esc(s.style.font)}</span></td>
      <td><span class="badge ${s.report.ok ? 'ok' : 'bad'}">проверки ${s.report.ok ? 'пройдены' : 'не пройдены'}</span>
        ${s.outdated ? '<span class="badge warn">карточку изменили после сборки</span>' : ''}
        <details><summary>Что проверялось</summary><ul>${checks}</ul></details></td>
      <td>${money(s.cost)}<br><span class="muted">${when(s.created_at)}</span></td>
      <td><a href="/preview/${s.id}/" target="_blank" rel="noopener">Предпросмотр</a><br>
        <a href="/api/sites/${s.id}/download">Скачать zip</a><br>
        <button class="link danger" data-del-site="${s.id}" data-name="сайт ${s.code} компании ${esc(s.brand)}">Удалить</button></td></tr>`;
  }).join('');
  return `<table><tr><th>ID</th>${withBrand ? '<th>Компания</th>' : ''}<th>Язык и стиль</th><th>Проверки</th><th>Расход</th><th></th></tr>${rows}</table>`;
}

async function showCompany(id) {
  await ensureModels();
  const [company, sites] = await Promise.all([api('/api/companies/' + id), api('/api/sites?company_id=' + id)]);
  spendBase.company = company.spend.total;
  const cat = config.catalog;
  const siteForm = company.status === 'approved'
    ? `<div class="panel"><form id="siteForm"><div class="row">
        <label>Язык сайта <select name="language">${options(cat.languages, false)}</select></label>
        <label>Шаблон <select name="theme">${options(config.themes, false)}</select></label>
        <label>Цветовая схема <select name="scheme">${options(config.schemes, false)}</select></label>
        <label>Шрифт заголовков <select name="font">${options(config.fonts, false)}</select></label>
      </div>
      <div class="row">${modelPicker('siteModel')}${limitPicker('siteLimit')}</div>
      <p class="muted">Модель нужна только для перевода, если язык сайта не совпадает с языком карточки (${esc(company.data.language)}). Без перевода запросов к OpenRouter нет.</p>
      <button type="submit">Создать версию сайта</button></form><div id="siteBox"></div></div>`
    : '<p class="muted">Сайт можно создать после утверждения комплекта.</p>';

  const tabs = cardTabs(company.data);
  view.innerHTML = `<h2>${esc(company.brand)} <span class="badge ${company.status}">${STATUS[company.status] || company.status}</span></h2>
    <div class="spend"><span>Потрачено на компанию</span><b id="spendCompany">${money(company.spend.total)}</b>
      <small>генерация ${money(company.spend.company)}${company.spend.sites ? `, переводы сайтов ${money(company.spend.sites)}` : ''}</small></div>
    <p class="muted">ID ${company.code}, модель ${esc(company.model)}
      <button class="link danger" data-del-company="${company.id}" data-name="${esc(company.brand)}">удалить компанию</button></p>
    <div id="msg">${issuesBox(company.issues)}</div>
    <div class="panel"><div class="row">${modelPicker('opModel')}${limitPicker('opLimit')}</div>
      <p class="muted">Модель и лимит для создания разделов и совместной проверки.</p><div id="opBox"></div></div>
    ${factsStep(company)}${aspectsStep(company)}${photosPanel(company)}${reviewStep(company)}${approveStep(company)}
    <h3>Карточка</h3>
    <div class="panel editor">
      <div class="editor-bar">
        <nav class="tabs">${tabs.map((t) => `<button type="button" class="tab" data-tab="${t.key}">${esc(t.title)}</button>`).join('')}</nav>
        <div class="editor-actions">
          <span id="dirty" class="muted" hidden>есть несохранённые правки</span>
          <button id="save">Сохранить</button>
          <a class="btn secondary" href="/api/companies/${company.id}/download">Скачать JSON</a>
        </div>
      </div>
      <form id="card">${tabs.map((t) => `<section class="tab-body" data-body="${t.key}" hidden>${tabHtml(company.data, t)}</section>`).join('')}</form>
    </div>
    <h3>Сайт</h3>${siteForm}
    <h3>Версии сайта</h3>${sitesTable(sites, false)}`;

  const msg = document.getElementById('msg');
  const form = document.getElementById('card');
  // style="" в разметке режет CSP, а так можно
  const photoRow = view.querySelector('.photos');
  if (photoRow) photoRow.style.setProperty('--n', company.data.people.length);

  // одна вкладка на экране, последнюю открытую помним
  const showTab = (key) => {
    view.querySelectorAll('.tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === key);
      //на телефоне вкладки прокручиваются, активную подвигаем в видимую часть
      if (b.dataset.tab === key) b.parentElement.scrollLeft = b.offsetLeft - 24;
    });
    form.querySelectorAll('.tab-body').forEach((s) => { s.hidden = s.dataset.body !== key; });
    form.querySelectorAll('textarea').forEach(autosize);
    remember('cardTab', key);
  };
  view.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  const saved = remember('cardTab');
  showTab(tabs.some((t) => t.key === saved) ? saved : tabs[0].key);
  form.addEventListener('input', (e) => {
    document.getElementById('dirty').hidden = false;
    if (e.target.tagName === 'TEXTAREA') autosize(e.target);
  });
  const opBox = document.getElementById('opBox');
  const op = () => ({ model: readModel('opModel'), max_cost: readLimit('opLimit') });

  // блокируем кнопки, ждём задачу, перерисовываем
  async function run(action, boxId = 'opBox', onStage = null) {
    const buttons = view.querySelectorAll('button');
    buttons.forEach((b) => { b.disabled = true; });
    const box = document.getElementById(boxId) || opBox;
    try {
      const job = await action();
      //id есть и у задачи и у компании, отличаем по stage
      if (job && 'stage' in job) {
        box.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const done = await waitJob(job.id, box, onStage);
        await showCompany(id);
        if (done.warning) document.getElementById('msg').innerHTML += `<div class="error">${esc(done.warning)}</div>`;
      } else {
        await showCompany(id);
      }
    } catch (err) {
      box.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  // в таблице: что готово, что делается, что ждёт
  const markRows = (keys) => (stage) => {
    const order = keys.map((k) => config.aspects.find((a) => a.key === k)).filter(Boolean);
    const current = order.findIndex((a) => stage === `Раздел: ${a.title}`);
    const reviewing = stage.startsWith('Совместная проверка');
    order.forEach((a, i) => {
      const cell = view.querySelector(`tr[data-row="${a.key}"] .mark`);
      if (!cell) return;
      if (reviewing || (current >= 0 && i < current)) cell.innerHTML = '<span class="badge ok">готово</span>';
      else if (i === current) cell.innerHTML = '<span class="badge warn"><span class="spinner"></span>создаётся</span>';
      else cell.innerHTML = '<span class="badge">в очереди</span>';
    });
  };
  //кого рисуем подсвечен, прошлые уже готовы
  const markPhoto = (stage) => {
    view.querySelectorAll('.photos li').forEach((li) => {
      const now = stage.endsWith(': ' + li.dataset.person);
      const state = li.querySelector('.state');
      if (li.classList.contains('busy') && !now) {
        li.classList.add('done');
        state.textContent = 'готово';
      }
      li.classList.toggle('busy', now);
      if (now) state.textContent = 'рисуется...';
    });
  };
  const have = Object.keys(company.data.sections || {});
  const planned = (company.state.planned || []).filter((k) => !have.includes(k));

  document.getElementById('save').addEventListener('click', async () => {
    try {
      const saved = await api('/api/companies/' + id, { method: 'PUT', body: JSON.stringify(collect(form, company.data)) });
      await showCompany(id);
      const note = saved.state.facts_approved ? 'Сохранено. Совместную проверку нужно пройти заново.' : 'Сохранено. Факты изменились, их нужно утвердить заново.';
      document.getElementById('msg').innerHTML += `<div class="success">${note}</div>`;
    } catch (err) {
      msg.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    }
  });

  const bind = (elId, action, boxId, onStage = null) => {
    const el = document.getElementById(elId);
    if (el) el.addEventListener('click', () => run(action, boxId, onStage));
  };
  bind('approveFacts', () => api(`/api/companies/${id}/approve-facts`, { method: 'POST' }), 'factsBox');
  bind('bulkSections', () => api(`/api/companies/${id}/sections`, { method: 'POST', body: JSON.stringify(op()) }),
    'sectionsBox', markRows(planned));
  bind('runReview', () => api(`/api/companies/${id}/review`, { method: 'POST', body: JSON.stringify(op()) }), 'reviewBox');
  bind('approve', () => api(`/api/companies/${id}/approve`, { method: 'POST' }), 'approveBox');
  const photoJob = (force, only = null) => api(`/api/companies/${id}/photos`, {
    method: 'POST', body: JSON.stringify({ model: readModel('photoModel'), max_cost: readLimit('photoLimit'), force, only }),
  });
  bind('makePhotos', () => photoJob(false), 'photoBox', markPhoto);
  bind('redoPhotos', () => photoJob(true), 'photoBox', markPhoto);
  // перерисовать одного
  view.querySelectorAll('[data-photo]').forEach((btn) => {
    btn.addEventListener('click', () => run(() => photoJob(true, Number(btn.dataset.photo)), 'photoBox', markPhoto));
  });

  document.querySelectorAll('[data-aspect]').forEach((btn) => {
    const key = btn.dataset.aspect;
    btn.addEventListener('click', () => run(() => {
      if (btn.dataset.action === 'remove') return api(`/api/companies/${id}/aspects/${key}`, { method: 'DELETE' });
      return api(`/api/companies/${id}/aspects/${key}`, { method: 'POST', body: JSON.stringify(op()) });
    }, 'sectionsBox', markRows([key])));
  });

  const siteEl = document.getElementById('siteForm');
  if (siteEl) {
    siteEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      const box = document.getElementById('siteBox');
      const body = Object.fromEntries(new FormData(e.target));
      body.company_id = Number(id);
      const btn = e.target.querySelector('button[type=submit]');
      btn.disabled = true;
      try {
        body.model = readModel('siteModel');
        body.max_cost = readLimit('siteLimit');
        const job = await api('/api/sites', { method: 'POST', body: JSON.stringify(body) });
        await waitJob(job.id, box);
        await showCompany(id);
      } catch (err) {
        box.innerHTML = `<div class="error">${esc(err.message)}</div>`;
        btn.disabled = false;
      }
    });
  }
}

// ---------- все сайты ----------

async function showSites() {
  const sites = await api('/api/sites');
  view.innerHTML = '<h2>Сайты</h2>' + sitesTable(sites, true);
}

// ---------- ключ OpenRouter ----------

function keyInfo(k) {
  if (!k.has_key) return '<p><span class="badge bad">ключ не задан</span> Генерация и перевод не работают.</p>';
  let extra = '';
  if (k.checked) {
    const limit = k.limit == null ? 'без лимита' : `лимит ${money(k.limit)}`;
    extra = `<br><span class="muted">OpenRouter принял ключ: ${limit}, потрачено ${money(k.usage || 0)}</span>`;
  } else if (k.checked === false) {
    extra = '<br><span class="muted">Проверить ключ у OpenRouter сейчас не получилось</span>';
  }
  return `<p><span class="badge ok">ключ задан</span> ${esc(k.hint)}, ${esc(k.source)}${extra}</p>`;
}

async function refreshKeyState() {
  config = await api('/api/config');
  const state = document.getElementById('keyState');
  state.innerHTML = `<span class="dot"></span>${config.has_key ? 'ключ задан' : 'ключ не задан'}`;
  state.title = config.has_key ? `Ключ OpenRouter задан ${config.key_source}` : 'Ключ OpenRouter не задан';
  state.className = config.has_key ? 'chip' : 'chip bad';
}

async function showKey(k) {
  if (!k) k = await api('/api/key?check=true');
  const form = k.editable
    ? `<form id="keyForm" autocomplete="off">
        <label>${k.has_key ? 'Новый ключ (заменит текущий)' : 'Ключ'}
          <input id="keyInput" type="password" autocomplete="new-password" spellcheck="false" placeholder="sk-or-v1-..." required></label>
        <div class="actions">
          <button type="submit">${k.has_key ? 'Заменить ключ' : 'Сохранить ключ'}</button>
          ${k.has_key ? '<button type="button" id="keyDelete" class="secondary">Удалить ключ</button>' : ''}
        </div>
      </form>`
    : `<div class="error">${esc(k.note)}</div>`;

  view.innerHTML = `<h2>Ключ OpenRouter</h2><div class="panel">
    ${keyInfo(k)}
    ${form}
    <div id="keyMsg"></div>
    <p class="muted">Ключ сохраняется на сервере в хранилище учётных данных системы и обратно в браузер не возвращается,
      видны только последние символы. Перед сохранением ключ проверяется у OpenRouter.
      На openrouter.ai у ключа стоит задать лимит кредитов: тогда даже утёкший ключ не потратит больше этой суммы.</p>
  </div>`;

  const msg = document.getElementById('keyMsg');
  const formEl = document.getElementById('keyForm');
  if (formEl) {
    formEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('keyInput');
      const btn = formEl.querySelector('button[type=submit]');
      btn.disabled = true;
      try {
        const saved = await api('/api/key', { method: 'PUT', body: JSON.stringify({ key: input.value }) });
        input.value = '';
        await refreshKeyState();
        await showKey(saved);
        document.getElementById('keyMsg').innerHTML = '<div class="success">Ключ сохранён.</div>';
      } catch (err) {
        input.value = '';
        btn.disabled = false;
        msg.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      }
    });
  }
  const del = document.getElementById('keyDelete');
  if (del) {
    del.addEventListener('click', async () => {
      if (!confirm('Удалить ключ? Генерация перестанет работать, пока не сохраните новый.')) return;
      try {
        const left = await api('/api/key', { method: 'DELETE' });
        await refreshKeyState();
        await showKey(left);
        document.getElementById('keyMsg').innerHTML = '<div class="success">Ключ удалён.</div>';
      } catch (err) {
        msg.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      }
    });
  }
}

// ---------- роутер ----------

async function route() {
  //счётчик компании только на её странице
  spendBase.company = null;
  refreshSpend();
  const [page, id] = location.hash.replace('#/', '').split('/');
  // карточка компании это тоже раздел «Компании»
  const tab = ['new', 'sites', 'key'].includes(page) ? page : 'list';
  document.querySelectorAll('.mainnav a').forEach((a) => a.classList.toggle('active', a.dataset.page === tab));
  try {
    if (page === 'new') await showNew();
    else if (page === 'company') await showCompany(id);
    else if (page === 'sites') await showSites();
    else if (page === 'key') await showKey();
    else await showList();
  } catch (err) {
    view.innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

// удаление ловим на всём view, кнопки перерисовываются вместе со страницей
async function onDelete(e) {
  const btn = e.target.closest('[data-del-company], [data-del-site]');
  if (!btn) return;
  const company = btn.dataset.delCompany;
  const text = company
    ? `Удалить компанию ${btn.dataset.name}? Вместе с ней удалятся все версии сайта и фото команды.`
    : `Удалить ${btn.dataset.name}? Файлы сайта тоже удалятся.`;
  if (!confirm(text)) return;
  try {
    const url = company ? '/api/companies/' + company : '/api/sites/' + btn.dataset.delSite;
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    // со страницы удалённой компании уходим в список
    if (company && location.hash.startsWith('#/company/')) location.hash = '#/';
    else route();
  } catch (err) {
    alert('Не удалось удалить: ' + err.message);
  }
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) { /* приватное окно */ }
}

async function init() {
  document.getElementById('themeToggle').addEventListener('click', toggleTheme);
  view.addEventListener('click', onDelete);
  await refreshKeyState();
  window.addEventListener('hashchange', route);
  route();
}

init().catch((err) => { view.innerHTML = `<div class="error">${esc(err.message)}</div>`; });
