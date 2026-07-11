// Recover from any previously-installed service worker (stale cache) without
// registering a new one — the kill-switch sw.js clears caches and unregisters.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistration().then((r) => { if (r) r.update(); }).catch(() => {});
}

const $ = (sel) => document.querySelector(sel);
const api = async (path, opts) => {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
};
const rupee = (n) => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2200);
}

// --- sidebar navigation -----------------------------------------------------
const TITLES = {
  dashboard: 'WhatsApp Dashboard', products: 'Products & Catalogue', orders: 'Orders',
  customers: 'Customers', referrals: 'Referrals & Wallet', chats: 'Live Messages',
  scan: 'Scan Lookup', bot: 'WhatsApp Bot', analytics: 'WhatsApp Analytics',
  templates: 'Message Templates', catalog: 'WhatsApp Catalog', settings: 'Settings',
};
function navTo(view) {
  document.querySelectorAll('.sb-item').forEach((t) => t.classList.toggle('active', t.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
  const t = $('#topTitle');
  if (t) t.textContent = TITLES[view] || view;
  const s = $('#globalSearch');
  if (s) { s.value = ''; }         // reset any active filter on tab switch
  render(view);
}
document.querySelectorAll('.sb-item[data-view]').forEach((item) =>
  item.addEventListener('click', () => navTo(item.dataset.view)));
const currentView = () => document.querySelector('.sb-item.active')?.dataset.view || 'dashboard';

// refresh with a little spin feedback
$('#refreshBtn')?.addEventListener('click', async (e) => {
  e.currentTarget.classList.add('spinning');
  try { await render(currentView()); } finally {
    setTimeout(() => e.currentTarget.classList.remove('spinning'), 400);
  }
});

// live search — filters the active view's tables + conversation list
$('#globalSearch')?.addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  const view = document.querySelector('.view.active');
  if (!view) return;
  view.querySelectorAll('table.data').forEach((tbl) => {
    let catRow = null, catHasMatch = false;
    const settleCat = () => { if (catRow) catRow.style.display = (q && !catHasMatch) ? 'none' : ''; };
    [...tbl.rows].forEach((row) => {
      if (row.querySelector('th')) return;                 // column header
      if (row.classList.contains('cat-row')) { settleCat(); catRow = row; catHasMatch = false; return; }
      const match = !q || row.textContent.toLowerCase().includes(q);
      row.style.display = match ? '' : 'none';
      if (match) catHasMatch = true;
    });
    settleCat();
  });
  view.querySelectorAll('.conv').forEach((c) => {
    c.style.display = (!q || c.textContent.toLowerCase().includes(q)) ? '' : 'none';
  });
});

function setNavCount(id, n) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = n;
  el.hidden = !n;
}

// --- renderers --------------------------------------------------------------
async function render(view) {
  document.body.classList.add('loading');   // top progress bar
  try {
    if (view === 'dashboard') await renderDashboard();
    if (view === 'products') await renderProducts();
    if (view === 'orders') await renderOrders();
    if (view === 'customers') await renderCustomers();
    if (view === 'referrals') await renderReferrals();
    if (view === 'chats') await renderChats();
    if (view === 'analytics') await renderAnalytics();
    if (view === 'templates') await renderTemplates();
    if (view === 'catalog') await renderCatalog();
    if (view === 'settings') await renderSettings();
    if (view === 'scan') $('#scanInput').focus();
  } catch (e) {
    toast('⚠️ ' + e.message);
  } finally {
    document.body.classList.remove('loading');
  }
}

function bar(label, value, max, suffix = '') {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return `<div class="bar-row"><span>${label}</span>
    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
    <span class="num">${suffix}${value}</span></div>`;
}

async function renderDashboard() {
  const s = await api('/reports/summary');
  $('#kpis').innerHTML = `
    ${kpi('Total revenue', rupee(s.totalRevenue), s.totalOrders + ' orders')}
    ${kpi('Today', rupee(s.todayRevenue), s.todayOrders + ' orders today')}
    ${kpi('Avg order', rupee(s.avgOrderValue), '')}
    ${kpi('Customers', s.customers, '')}
  `;
  const maxRev = Math.max(1, ...s.series.map((d) => d.revenue));
  $('#revenueBars').innerHTML = s.series
    .map((d) => bar(d.date.slice(5), d.revenue, maxRev, '₹')).join('') || '<p class="muted">No data yet.</p>';

  const maxQty = Math.max(1, ...s.topProducts.map((p) => p.qty));
  $('#topProducts').innerHTML = s.topProducts.length
    ? s.topProducts.map((p) => `<li><span>${p.emoji} ${p.name}</span><span class="pill">${p.qty} sold · ${rupee(p.revenue)}</span></li>`).join('')
    : '<li class="muted">No sales yet — try the WhatsApp bot!</li>';

  $('#lowStock').innerHTML = s.lowStock.length
    ? s.lowStock.map((p) => `<li><span>${p.emoji} ${p.name}</span><span class="pill warn">${p.stock} ${p.unit} left</span></li>`).join('')
    : '<li class="muted">All stocked up ✅</li>';

  const maxCh = Math.max(1, s.channels.whatsapp, s.channels.manual);
  $('#channels').innerHTML = bar('WhatsApp', s.channels.whatsapp, maxCh) + bar('Manual', s.channels.manual, maxCh);

  // referral liability (MIS / accounting view)
  try {
    const l = await api('/referrals/liability');
    $('#kpis').innerHTML += kpi('Referral liability', rupee(l.outstandingLiability), 'pending payout');
  } catch { /* referrals optional */ }

  await loadPaymentSettings();
}

// --- payment setup ------------------------------------------------------------
async function loadPaymentSettings() {
  const p = await api('/settings/payment');
  $('#payCod').checked = p.codEnabled;
  $('#payUpi').checked = p.upiToggle;
  $('#payVpa').value = p.upiVpa || '';
  $('#payName').value = p.upiName || '';
  $('#payHint').textContent = p.upiToggle && !p.upiVpa
    ? '⚠️ UPI is on but no UPI ID is set — the bot will only offer cash until you add one.'
    : (p.upiEnabled ? '✅ Customers can choose cash or UPI at checkout.' : 'Customers currently pay cash on delivery.');
}
$('#payForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await api('/settings/payment', {
    method: 'PATCH',
    body: JSON.stringify({
      codEnabled: $('#payCod').checked,
      upiEnabled: $('#payUpi').checked,
      upiVpa: $('#payVpa').value.trim(),
      upiName: $('#payName').value.trim(),
    }),
  });
  toast('💳 Payment setup saved');
  await loadPaymentSettings();
});

const kpi = (label, value, sub) =>
  `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;

// --- Analytics (Chart.js) -----------------------------------------------------
const PALETTE = ['#25D366', '#075E54', '#2563EB', '#7C3AED', '#F9C74F', '#E63946', '#1B8B4B', '#F97316'];
const charts = {};
function makeChart(id, cfg) {
  const el = document.getElementById(id);
  if (!el) return;
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(el, cfg);
}

async function renderAnalytics() {
  if (typeof Chart === 'undefined') {
    $('#anKpis').innerHTML = '<div class="card">📉 Charts need the Chart.js library, which failed to load (offline?). The rest of the dashboard works fine.</div>';
    return;
  }
  const [s, orders] = await Promise.all([api('/reports/summary'), api('/orders')]);

  $('#anKpis').innerHTML = `
    ${kpi('Total revenue', rupee(s.totalRevenue), s.totalOrders + ' orders')}
    ${kpi('WhatsApp orders', s.channels.whatsapp, 'vs ' + s.channels.manual + ' manual')}
    ${kpi('Avg order value', rupee(s.avgOrderValue), '')}
    ${kpi('Customers', s.customers, '')}`;

  const gridColor = 'rgba(0,0,0,0.05)';
  const noAxis = { plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 12 }, padding: 14 } } }, cutout: '68%', responsive: true, maintainAspectRatio: false };

  // orders-per-day aligned to the revenue series
  const perDay = Object.fromEntries(s.series.map((d) => [d.date, 0]));
  for (const o of orders) {
    const day = (o.createdAt || '').slice(0, 10);
    if (day in perDay) perDay[day] += 1;
  }
  makeChart('chRevenue', {
    type: 'bar',
    data: {
      labels: s.series.map((d) => d.date.slice(5)),
      datasets: [
        { label: 'Revenue (₹)', data: s.series.map((d) => d.revenue), backgroundColor: 'rgba(37,211,102,0.75)', borderRadius: 6, yAxisID: 'y' },
        { label: 'Orders', data: s.series.map((d) => perDay[d.date]), backgroundColor: 'rgba(7,94,84,0.55)', borderRadius: 6, yAxisID: 'y1' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } } },
      scales: {
        y: { position: 'left', beginAtZero: true, grid: { color: gridColor }, ticks: { font: { size: 10 } } },
        y1: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { font: { size: 10 }, precision: 0 } },
        x: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
    },
  });

  makeChart('chChannels', {
    type: 'doughnut',
    data: { labels: ['WhatsApp', 'Manual'], datasets: [{ data: [s.channels.whatsapp, s.channels.manual], backgroundColor: ['#25D366', '#2563EB'], borderWidth: 0, hoverOffset: 6 }] },
    options: noAxis,
  });

  const top = s.topProducts.slice(0, 6);
  makeChart('chTop', {
    type: 'bar',
    data: { labels: top.map((p) => p.name), datasets: [{ label: 'Sold', data: top.map((p) => p.qty), backgroundColor: top.map((_, i) => PALETTE[i % PALETTE.length]), borderRadius: 6 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, grid: { color: gridColor }, ticks: { font: { size: 10 }, precision: 0 } }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } },
    },
  });

  const payTally = {};
  for (const o of orders) { const m = o.paymentMode || 'unset'; payTally[m] = (payTally[m] || 0) + 1; }
  const payLabels = Object.keys(payTally);
  makeChart('chPay', {
    type: 'doughnut',
    data: { labels: payLabels.map((m) => m.toUpperCase()), datasets: [{ data: payLabels.map((m) => payTally[m]), backgroundColor: payLabels.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0, hoverOffset: 6 }] },
    options: noAxis,
  });

  const STAGES = ['placed', 'packed', 'out_for_delivery', 'delivered', 'cancelled'];
  const statusTally = Object.fromEntries(STAGES.map((s2) => [s2, 0]));
  for (const o of orders) if (o.status in statusTally) statusTally[o.status] += 1;
  makeChart('chStatus', {
    type: 'bar',
    data: { labels: STAGES.map((s2) => s2.replace(/_/g, ' ')), datasets: [{ label: 'Orders', data: STAGES.map((s2) => statusTally[s2]), backgroundColor: ['#F9C74F', '#2563EB', '#7C3AED', '#1B8B4B', '#E63946'], borderRadius: 6 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, grid: { color: gridColor }, ticks: { font: { size: 10 }, precision: 0 } }, x: { grid: { display: false }, ticks: { font: { size: 11 } } } },
    },
  });
}

let categoryState = {};   // name -> active (for catalogue headers)

async function renderCategories() {
  const cats = await api('/categories');
  categoryState = Object.fromEntries(cats.map((c) => [c.name, c.active]));
  $('#catChips').innerHTML = cats.map((c) => `
    <span class="cat-chip ${c.active ? '' : 'off'}">
      <b>${c.name}</b>
      <span class="pill">${c.productCount}</span>
      <button type="button" class="chip-act" data-toggle="${c.id}" data-next="${!c.active}"
        title="${c.active ? 'Deactivate — hides its products from the bot menu' : 'Activate'}">
        ${c.active ? '⏸' : '▶'}
      </button>
      <button type="button" class="chip-act danger" data-delcat="${c.id}"
        ${c.productCount ? 'disabled title="Has products — reassign them first"' : 'title="Delete category"'}>✕</button>
    </span>`).join('') || '<span class="muted">No categories yet.</span>';

  document.querySelectorAll('[data-toggle]').forEach((b) =>
    b.addEventListener('click', async () => {
      await api('/categories/' + b.dataset.toggle, { method: 'PATCH', body: JSON.stringify({ active: b.dataset.next === 'true' }) });
      toast(b.dataset.next === 'true' ? 'Category activated' : 'Category deactivated — hidden from bot menu');
      renderProducts();
    }));
  document.querySelectorAll('[data-delcat]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (b.disabled) return;
      if (!confirm('Delete this category?')) return;
      try {
        await api('/categories/' + b.dataset.delcat, { method: 'DELETE' });
        toast('Category deleted');
      } catch (err) { toast('⚠️ ' + err.message); }
      renderProducts();
    }));
}

$('#catForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('#catName').value.trim();
  if (!name) return;
  try {
    await api('/categories', { method: 'POST', body: JSON.stringify({ name }) });
    $('#catName').value = '';
    toast(`Category "${name}" added`);
    renderProducts();
  } catch (err) { toast('⚠️ ' + err.message); }
});

async function renderProducts() {
  await renderCategories();
  const products = await api('/products');

  // group by category
  const groups = {};
  for (const p of products) {
    const cat = p.category || 'Other';
    (groups[cat] = groups[cat] || []).push(p);
  }
  const categories = Object.keys(groups).sort();

  // feed the add-dialog's category suggestions
  $('#categoryList').innerHTML = categories.map((c) => `<option value="${c}">`).join('');

  let html = `<tr><th>Product</th><th>Category</th><th>Price</th><th>Cost</th><th>Stock</th><th>Ref. bonus</th><th>Cap</th><th>Loyalty</th><th></th></tr>`;
  for (const cat of categories) {
    const inactiveCat = categoryState[cat] === false;
    html += `<tr class="cat-row${inactiveCat ? ' cat-off' : ''}"><td colspan="9">${cat} <span class="muted">(${groups[cat].length})</span>${inactiveCat ? ' <span class="tag cancelled">hidden from menu</span>' : ''}</td></tr>`;
    html += groups[cat].map((p) => {
      const pct = (p.cost != null && p.price > 0) ? Math.round(((p.price - p.cost) / p.price) * 100) : null;
      return `
      <tr>
        <td>${p.emoji} ${p.name}</td>
        <td><input class="inline-input cat" type="text" list="categoryList" value="${p.category || ''}" data-field="category" data-id="${p.id}" /></td>
        <td>${rupee(p.price)}/${p.unit}</td>
        <td><input class="inline-input sm" type="number" value="${p.cost ?? ''}" data-field="cost" data-id="${p.id}" placeholder="—" />${pct != null ? `<div class="hint">${pct}% margin</div>` : ''}</td>
        <td><input class="inline-input sm" type="number" value="${p.stock}" data-field="stock" data-id="${p.id}" /></td>
        <td>
          <select class="mini" data-field="ref_bonus_type" data-id="${p.id}">
            <option value="percent" ${p.ref_bonus_type === 'percent' ? 'selected' : ''}>%</option>
            <option value="flat" ${p.ref_bonus_type === 'flat' ? 'selected' : ''}>₹</option>
          </select>
          <input class="inline-input sm" type="number" value="${p.ref_bonus_value}" data-field="ref_bonus_value" data-id="${p.id}" />
        </td>
        <td><input class="inline-input sm" type="number" value="${p.ref_cap || ''}" data-field="ref_cap" data-id="${p.id}" placeholder="∞" /></td>
        <td>
          <select class="mini" data-field="loyalty_bonus_type" data-id="${p.id}">
            <option value="percent" ${p.loyalty_bonus_type === 'percent' ? 'selected' : ''}>%</option>
            <option value="flat" ${p.loyalty_bonus_type === 'flat' ? 'selected' : ''}>₹</option>
          </select>
          <input class="inline-input sm" type="number" value="${p.loyalty_bonus_value}" data-field="loyalty_bonus_value" data-id="${p.id}" />
        </td>
        <td><span class="linkish" data-del="${p.id}">Delete</span></td>
      </tr>`;
    }).join('');
  }
  $('#productsTable').innerHTML = html;

  const TEXT_FIELDS = ['category', 'name', 'ref_bonus_type', 'loyalty_bonus_type'];
  const save = async (el) => {
    const field = el.dataset.field;
    let v;
    if (el.tagName === 'SELECT' || TEXT_FIELDS.includes(field)) {
      v = el.value.trim();
      if (!v && field === 'category') { toast('Category cannot be empty'); return false; }
    } else {
      v = el.value === '' ? null : Number(el.value);
    }
    await api('/products/' + el.dataset.id, { method: 'PATCH', body: JSON.stringify({ [field]: v }) });
    toast('Saved');
    return true;
  };
  document.querySelectorAll('#productsTable [data-field]').forEach((el) => {
    el.addEventListener('change', async () => {
      const ok = await save(el);
      if (ok && (el.dataset.field === 'cost' || el.dataset.field === 'category')) renderProducts();
    });
  });
  document.querySelectorAll('[data-del]').forEach((el) => {
    el.addEventListener('click', async () => {
      if (!confirm('Delete this product?')) return;
      await api('/products/' + el.dataset.del, { method: 'DELETE' });
      toast('Deleted');
      renderProducts();
    });
  });
}

async function renderOrders() {
  const orders = await api('/orders');
  setNavCount('navOrders', orders.length);
  const next = { placed: 'packed', packed: 'out_for_delivery', out_for_delivery: 'delivered' };
  const rows = orders.map((o) => {
    const items = o.items.map((l) => `${l.emoji}×${l.qty}`).join(' ');
    const advance = next[o.status]
      ? `<button class="mini" data-next="${o.id}" data-to="${next[o.status]}">→ ${next[o.status].replace(/_/g, ' ')}</button>`
      : '';
    return `<tr>
      <td><b>${o.code}</b></td>
      <td>${o.phone}${o.address ? `<div class="hint">📍 ${o.address}</div>` : ''}</td>
      <td>${items}</td>
      <td>${rupee(o.total)}${o.walletUsed ? `<div class="hint">👛 -${rupee(o.walletUsed)}</div>` : ''}</td>
      <td><span class="tag ${o.channel}">${o.channel}</span></td>
      <td>${o.paymentMode
        ? `<span class="tag ${o.paymentStatus === 'paid' ? 'delivered' : 'placed'}">${o.paymentMode} · ${o.paymentStatus || ''}</span>
           ${o.paymentStatus === 'pending' && o.total > 0 ? `<button class="mini" data-paid="${o.id}" title="Mark payment received">💰</button>` : ''}`
        : '<span class="muted">—</span>'}</td>
      <td><span class="tag ${o.status}">${o.status.replace(/_/g, ' ')}</span></td>
      <td>${advance} <a class="mini slip-btn" href="/api/orders/${o.id}/slip" target="_blank" title="Barcode delivery slip (PDF)">🧾</a></td>
    </tr>`;
  }).join('');
  $('#ordersTable').innerHTML =
    `<tr><th>Code</th><th>Phone</th><th>Items</th><th>Total</th><th>Channel</th><th>Payment</th><th>Status</th><th></th></tr>${rows || '<tr><td colspan="8" class="muted">No orders yet.</td></tr>'}`;

  document.querySelectorAll('[data-paid]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await api('/orders/' + btn.dataset.paid, { method: 'PATCH', body: JSON.stringify({ payment_status: 'paid' }) });
      toast('💰 Marked paid');
      renderOrders();
    });
  });

  document.querySelectorAll('[data-next]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await api('/orders/' + btn.dataset.next, { method: 'PATCH', body: JSON.stringify({ status: btn.dataset.to }) });
      renderOrders();
    });
  });
}

async function renderCustomers() {
  const customers = await api('/customers');
  const rows = customers.map((c) => `
    <tr>
      <td>${c.name}${c.referredBy ? `<div class="hint">via ${c.referredBy}</div>` : ''}</td>
      <td>${c.phone}${c.address ? `<div class="hint">📍 ${c.address}</div>` : ''}</td>
      <td><code>${c.referralCode || '—'}</code></td>
      <td>${c.orderCount}</td>
      <td>${rupee(c.totalSpent)}</td>
      <td>${rupee(c.walletBalance)}${c.walletPending ? `<div class="hint">+${rupee(c.walletPending)} pending</div>` : ''}</td>
    </tr>`).join('');
  $('#customersTable').innerHTML =
    `<tr><th>Name</th><th>Phone</th><th>Ref code</th><th>Orders</th><th>Spent</th><th>Wallet</th></tr>${rows || '<tr><td colspan="6" class="muted">No customers yet.</td></tr>'}`;
}

async function renderReferrals() {
  const [liab, referrers] = await Promise.all([
    api('/referrals/liability'),
    api('/referrals'),
  ]);

  $('#refKpis').innerHTML = `
    ${kpi('Outstanding liability', rupee(liab.outstandingLiability), 'provisional + review')}
    ${kpi('Paid to wallets', rupee(liab.paidOut), 'approved')}
    ${kpi('Wallet float', rupee(liab.walletFloat), rupee(liab.redeemed) + ' redeemed')}
    ${kpi('Referral accrued', rupee(liab.referralAccrued), 'referrer bonuses')}
    ${kpi('Loyalty accrued', rupee(liab.loyaltyAccrued), (liab.loyaltyRate || 0) + '% cashback')}
  `;
  $('#refRules').textContent =
    `Referrers earn the item-wise bonus on every order a referred customer places, and every ` +
    `customer earns item-wise loyalty cashback on their own orders (default ${liab.loyaltyRate}%, set per product in the catalogue). ` +
    `Rewards clear after delivery + ${liab.returnWindowDays}-day return window, then land in the wallet ` +
    `(spendable at checkout). Margin guard: a referral bonus above ${Math.round(liab.marginGuardFraction * 100)}% of line margin is held for review.`;

  const rRows = referrers.map((r) => `
    <tr>
      <td>${r.name}</td>
      <td><code>${r.code}</code></td>
      <td>${r.referredCustomers}</td>
      <td>${r.referredOrders}</td>
      <td>${rupee(r.provisional)}</td>
      <td>${rupee(r.review)}</td>
      <td><b>${rupee(r.walletBalance)}</b></td>
    </tr>`).join('');
  $('#referrersTable').innerHTML =
    `<tr><th>Referrer</th><th>Code</th><th>Referred</th><th>Orders</th><th>Pending</th><th>Review</th><th>Wallet</th></tr>${rRows || '<tr><td colspan="7" class="muted">No referrers yet. Use the bot: type <code>mycode</code>, then <code>ref &lt;CODE&gt;</code> from another number.</td></tr>'}`;

  renderAiSuggestions();
  await renderLedger();
}

// --- AI assistant -----------------------------------------------------------
const AI_SUGGESTIONS = [
  "What's our outstanding referral liability?",
  "Who is our top referrer and how much have they earned?",
  "How much is pending vs already paid to wallets?",
  "Summarize today's sales and referral exposure.",
];
function renderAiSuggestions() {
  const el = $('#aiSuggestions');
  if (!el) return;
  el.innerHTML = AI_SUGGESTIONS.map((s) => `<button type="button" class="mini ai-sugg">${s}</button>`).join('');
  el.querySelectorAll('.ai-sugg').forEach((b) =>
    b.addEventListener('click', () => { $('#aiText').value = b.textContent; $('#aiForm').requestSubmit(); }));
}
$('#aiForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = $('#aiText').value.trim();
  if (!q) return;
  $('#aiAnswer').classList.remove('muted');
  $('#aiAnswer').textContent = '🤔 Thinking…';
  try {
    const r = await api('/assistant', { method: 'POST', body: JSON.stringify({ question: q }) });
    $('#aiAnswer').textContent = r.answer;
  } catch (err) {
    $('#aiAnswer').textContent = '⚠️ ' + err.message;
  }
});

async function renderLedger() {
  const filter = $('#ledgerFilter').value;
  const entries = await api('/referrals/ledger' + (filter ? '?status=' + filter : ''));
  const reasonLabel = {
    self_referral: 'self-referral', cap_breach: 'cap breach',
    return_window: 'return window', low_margin: 'low margin',
  };
  const rows = entries.map((e) => {
    const actions = (e.status === 'review' || e.status === 'provisional')
      ? `<button class="mini" data-approve="${e.id}">Approve</button> <button class="mini" data-reverse="${e.id}">Reverse</button>`
      : '';
    const kindTag = e.kind === 'loyalty'
      ? '<span class="badge b-purple">🎁 loyalty</span>'
      : '<span class="badge b-wa">👥 referral</span>';
    const flow = e.kind === 'loyalty' ? `${e.referrerName}` : `${e.referredName} → ${e.referrerName}`;
    return `<tr>
      <td><b>${e.orderCode}</b></td>
      <td>${kindTag}</td>
      <td>${flow}</td>
      <td>${e.itemName || '—'}</td>
      <td>${rupee(e.reward)}</td>
      <td><span class="tag ${e.status}">${e.status}</span>${e.reviewReason ? `<div class="hint">${reasonLabel[e.reviewReason] || e.reviewReason}</div>` : ''}</td>
      <td>${actions}</td>
    </tr>`;
  }).join('');
  $('#ledgerTable').innerHTML =
    `<tr><th>Order</th><th>Type</th><th>Earner</th><th>Item</th><th>Reward</th><th>State</th><th></th></tr>${rows || '<tr><td colspan="7" class="muted">No ledger entries yet.</td></tr>'}`;

  const act = async (id, status) => {
    await api('/referrals/ledger/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    toast(status === 'approved' ? 'Approved → wallet' : 'Reversed');
    renderReferrals();
  };
  document.querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', () => act(b.dataset.approve, 'approved')));
  document.querySelectorAll('[data-reverse]').forEach((b) => b.addEventListener('click', () => act(b.dataset.reverse, 'reversed')));
}

// --- referrals controls -----------------------------------------------------
$('#processBtn').addEventListener('click', async () => {
  const r = await api('/referrals/process', { method: 'POST' });
  toast(r.approved ? `Approved ${r.approved} → ${rupee(r.total)} to wallets` : 'Nothing eligible yet');
  renderReferrals();
});
$('#ledgerFilter').addEventListener('change', renderLedger);

// --- add product (dialog) -----------------------------------------------------
$('#addProductBtn').addEventListener('click', () => {
  $('#productForm').reset();
  $('#pfEmoji').value = '🍎';
  $('#pfStock').value = 50;
  $('#productDialog').showModal();
  $('#pfName').focus();
});
$('#pfCancel').addEventListener('click', () => $('#productDialog').close());
$('#productForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    name: $('#pfName').value.trim(),
    emoji: $('#pfEmoji').value.trim() || '🍎',
    category: $('#pfCategory').value.trim() || 'Other',
    unit: $('#pfUnit').value,
    price: Number($('#pfPrice').value),
    stock: Number($('#pfStock').value) || 0,
  };
  const cost = $('#pfCost').value;
  if (cost !== '') body.cost = Number(cost);
  if (!body.name || !body.price) { toast('Name and price are required'); return; }
  await api('/products', { method: 'POST', body: JSON.stringify(body) });
  $('#productDialog').close();
  toast(`Added ${body.emoji} ${body.name} to ${body.category}`);
  renderProducts();
});

// --- Broadcast ----------------------------------------------------------------
async function refreshBroadcast() {
  const audience = $('#bcAudience').value;
  try {
    const [size, history] = await Promise.all([
      api('/broadcast/audience/' + audience),
      api('/broadcast'),
    ]);
    $('#bcReach').textContent = `reaches ${size.recipients} customer${size.recipients === 1 ? '' : 's'}`;
    $('#bcHistory').innerHTML = history.map((b) => `
      <li><span>${b.message.slice(0, 60)}${b.message.length > 60 ? '…' : ''}</span>
      <span class="pill">${b.audience} · ${b.recipients} sent · ${new Date(b.createdAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span></li>`).join('')
      || '<li class="muted">No broadcasts sent yet.</li>';
  } catch { /* ignore while server restarts */ }
}
$('#bcAudience').addEventListener('change', refreshBroadcast);
$('#bcForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = $('#bcText').value.trim();
  if (!message) return;
  const audience = $('#bcAudience').value;
  const r = await api('/broadcast', { method: 'POST', body: JSON.stringify({ message, audience }) });
  $('#bcText').value = '';
  toast(`📣 Broadcast sent to ${r.sent} customer${r.sent === 1 ? '' : 's'}`);
  await refreshBroadcast();
  await renderChats();
});

// --- Chats (admin live messages) ---------------------------------------------
let currentChat = null;

async function renderChats() {
  await refreshBroadcast();
  const chats = await api('/chats');
  setNavCount('navChats', chats.reduce((n, c) => n + (c.unread || 0), 0) || chats.length);
  $('#chatsCount').textContent = chats.length + ' conversation' + (chats.length === 1 ? '' : 's');
  $('#convList').innerHTML = chats.map((c) => `
    <button type="button" class="conv ${c.phone === currentChat ? 'active' : ''}" data-phone="${c.phone}">
      <span class="conv-avatar">${(c.name || 'W').slice(0, 1).toUpperCase()}</span>
      <span class="conv-body">
        <span class="conv-top"><b>${c.name}</b><span class="conv-time">${new Date(c.lastAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span></span>
        <span class="conv-last">${c.lastSource === 'customer' ? '' : (c.lastSource === 'admin' ? 'You: ' : '🤖 ')}${c.lastText}</span>
        <span class="conv-phone">${c.phone}</span>
      </span>
    </button>`).join('') || '<p class="muted" style="padding:12px">No conversations yet — try the WhatsApp Bot tab.</p>';

  document.querySelectorAll('.conv').forEach((el) =>
    el.addEventListener('click', () => openChat(el.dataset.phone)));

  if (currentChat) await loadChatMessages(currentChat, true);
}

async function openChat(phone) {
  currentChat = phone;
  $('#adminChatText').disabled = false;
  $('#adminChatSend').disabled = false;
  $('#tplPickBtn').disabled = false;
  document.querySelectorAll('.conv').forEach((el) =>
    el.classList.toggle('active', el.dataset.phone === phone));
  await loadChatMessages(phone, false);
  $('#adminChatText').focus();
}

async function loadChatMessages(phone, quiet) {
  const h = await api('/chats/' + encodeURIComponent(phone));
  $('#chatHead').innerHTML = `<b>${h.name}</b> <span class="muted">· ${h.phone}</span>`;
  const el = $('#adminChat');
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  el.innerHTML = h.messages.map((m) => `
    <div class="msg ${m.source === 'customer' ? 'bot' : 'me'}">
      ${m.source !== 'customer' ? `<div class="msg-tag">${m.source === 'admin' ? '👨‍💼 you' : '🤖 bot'}</div>` : ''}
      ${md(m.text)}
    </div>`).join('');
  if (!quiet || atBottom) el.scrollTop = el.scrollHeight;
}

$('#adminChatForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('#adminChatText').value.trim();
  if (!text || !currentChat) return;
  $('#adminChatText').value = '';
  await api('/chats/' + encodeURIComponent(currentChat) + '/send', {
    method: 'POST', body: JSON.stringify({ message: text }),
  });
  await loadChatMessages(currentChat, false);
});

// auto-refresh the inbox while it's open
setInterval(() => {
  if (currentView() === 'chats') renderChats().catch(() => {});
}, 5000);

// --- Settings (WhatsApp / Meta config) ----------------------------------------
async function renderSettings() {
  const w = await api('/settings/whatsapp');
  const st = $('#waStatus');
  st.textContent = w.connected ? '● connected' : '○ not connected';
  st.className = 'badge ' + (w.connected ? 'b-green' : 'b-gray');
  $('#waToken').value = '';
  $('#waToken').placeholder = w.tokenSet ? `token saved (${w.tokenHint}) — leave blank to keep` : 'EAAG… paste your token';
  $('#waPhoneId').value = w.phoneId || '';
  $('#waWabaId').value = w.wabaId || '';
  $('#waVerify').value = w.verifyToken || '';
  $('#waHint').textContent = w.connected
    ? '✅ Live — the bot & broadcasts send to real WhatsApp.'
    : 'Not connected — messages run in simulator/dry-run mode until you add a token + phone ID.';
  $('#waCallback').textContent = location.origin + '/api/whatsapp/webhook';
  $('#waVerifyShow').textContent = w.verifyToken || 'hsfoods-verify';
}
$('#waForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    phoneId: $('#waPhoneId').value.trim(),
    wabaId: $('#waWabaId').value.trim(),
    verifyToken: $('#waVerify').value.trim(),
  };
  if ($('#waToken').value.trim()) body.token = $('#waToken').value.trim();
  await api('/settings/whatsapp', { method: 'PATCH', body: JSON.stringify(body) });
  toast('⚙️ WhatsApp setup saved');
  await renderSettings();
});

// --- Message Templates --------------------------------------------------------
const TPL_CAT_CLASS = { 'Status update': 'b-blue', 'Payment': 'b-yellow', 'Marketing': 'b-purple', 'Order placed': 'b-wa' };

async function renderTemplates() {
  const tpls = await api('/templates');
  $('#tplGrid').innerHTML = tpls.map((t) => `
    <div class="card tpl-card">
      <div class="tpl-card-head">
        <div>
          <div class="tpl-name">${t.name}</div>
          <div class="hint">Used ${t.used}×</div>
        </div>
        <span class="badge ${TPL_CAT_CLASS[t.category] || 'b-gray'}">${t.category}</span>
      </div>
      <div class="tpl-body">${md(t.body)}</div>
      <div class="tpl-actions">
        <button class="mini" data-tpl-edit="${t.id}">Edit</button>
        <button class="linkish" data-tpl-del="${t.id}">Delete</button>
      </div>
    </div>`).join('') || '<p class="muted">No templates yet.</p>';

  document.querySelectorAll('[data-tpl-edit]').forEach((b) =>
    b.addEventListener('click', () => openTemplateDialog(tpls.find((t) => t.id === b.dataset.tplEdit))));
  document.querySelectorAll('[data-tpl-del]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (!confirm('Delete this template?')) return;
      await api('/templates/' + b.dataset.tplDel, { method: 'DELETE' });
      toast('Template deleted');
      renderTemplates();
    }));
}

function openTemplateDialog(t) {
  $('#tplDlgTitle').textContent = t ? 'Edit template' : 'New template';
  $('#tfId').value = t ? t.id : '';
  $('#tfName').value = t ? t.name : '';
  $('#tfCategory').value = t ? t.category : 'General';
  $('#tfBody').value = t ? t.body : '';
  $('#templateDialog').showModal();
  $('#tfName').focus();
}
$('#addTemplateBtn').addEventListener('click', () => openTemplateDialog(null));
$('#tfCancel').addEventListener('click', () => $('#templateDialog').close());
$('#templateForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('#tfId').value;
  const body = { name: $('#tfName').value.trim(), category: $('#tfCategory').value.trim() || 'General', body: $('#tfBody').value };
  if (!body.name || !body.body.trim()) { toast('Name and message required'); return; }
  if (id) await api('/templates/' + id, { method: 'PATCH', body: JSON.stringify(body) });
  else await api('/templates', { method: 'POST', body: JSON.stringify(body) });
  $('#templateDialog').close();
  toast('Template saved');
  renderTemplates();
});

// template picker for the Live Messages inbox
$('#tplPickBtn').addEventListener('click', async () => {
  if (!currentChat) return;
  const tpls = await api('/templates');
  $('#tplPickerList').innerHTML = tpls.map((t) => `
    <button type="button" class="tpl-pick" data-pick="${t.id}">
      <div class="tpl-name">${t.name} <span class="badge ${TPL_CAT_CLASS[t.category] || 'b-gray'}">${t.category}</span></div>
      <div class="tpl-body">${md(t.body)}</div>
    </button>`).join('') || '<p class="muted">No templates yet — create some in Message Templates.</p>';
  $('#tplPickerDialog').showModal();
  document.querySelectorAll('[data-pick]').forEach((b) =>
    b.addEventListener('click', async () => {
      const { text } = await api('/templates/' + b.dataset.pick + '/render?phone=' + encodeURIComponent(currentChat), { method: 'POST' });
      $('#adminChatText').value = text;
      $('#tplPickerDialog').close();
      $('#adminChatText').focus();
    }));
});
$('#tplPickerClose').addEventListener('click', () => $('#tplPickerDialog').close());

// --- WA Catalog ---------------------------------------------------------------
async function renderCatalog() {
  const [products, cats] = await Promise.all([api('/products'), api('/categories')]);
  const active = Object.fromEntries(cats.map((c) => [c.name, c.active]));
  const groups = {};
  for (const p of products) (groups[p.category || 'Other'] = groups[p.category || 'Other'] || []).push(p);

  $('#catalogGrid').innerHTML = Object.keys(groups).sort().map((cat) => `
    <div class="card">
      <div class="card-head">
        <h3>${cat} <span class="muted">(${groups[cat].length})</span></h3>
        ${active[cat] === false ? '<span class="badge b-gray">hidden from menu</span>' : '<span class="badge b-wa">live</span>'}
      </div>
      <div class="cat-cards">
        ${groups[cat].map((p) => `
          <div class="cat-item ${p.stock <= 0 ? 'oos' : ''}">
            <div class="cat-emoji">${p.emoji}</div>
            <div class="cat-item-name">${p.name}</div>
            <div class="cat-item-price">${rupee(p.price)}<span>/${p.unit}</span></div>
            <div class="cat-item-stock">${p.stock > 0 ? p.stock + ' in stock' : 'out of stock'}</div>
          </div>`).join('')}
      </div>
    </div>`).join('') || '<p class="muted">No products yet.</p>';
}

$('#shareCatalogBtn').addEventListener('click', async () => {
  const products = await api('/products');
  const lines = products.filter((p) => p.stock > 0).map((p) => `${p.emoji} ${p.name} — ${rupee(p.price)}/${p.unit}`);
  const text = "🍃 *HSFOODS — Fresh today!*\n\n" + lines.join('\n') + "\n\nReply *menu* to order — delivered in 10 minutes! ⚡";
  navTo('chats');
  setTimeout(() => { const t = $('#bcText'); if (t) { t.value = text; t.focus(); toast('📤 Catalogue loaded into Broadcast — pick an audience & send'); } }, 300);
});

// --- Scan lookup ---------------------------------------------------------------
const NEXT_STATUS = { placed: 'packed', packed: 'out_for_delivery', out_for_delivery: 'delivered' };

async function scanLookup(code) {
  code = code.trim().toUpperCase();
  if (!code) return;
  const box = $('#scanResult');
  try {
    const o = await api('/orders/' + encodeURIComponent(code));
    renderScanOrder(o);
  } catch {
    box.innerHTML = `<div class="scan-miss">❌ No order found for <b>${code}</b></div>`;
  }
  $('#scanInput').select();
  $('#scanInput').focus();
}

function renderScanOrder(o) {
  const items = o.items.map((l) =>
    `<li><span>${l.emoji} ${l.name} ×${l.qty}</span><span>${rupee(l.price * l.qty)}</span></li>`).join('');
  const next = NEXT_STATUS[o.status];
  $('#scanResult').innerHTML = `
    <div class="scan-order">
      <div class="scan-head">
        <div><div class="scan-code">${o.code}</div>
        <span class="tag ${o.status}">${o.status.replace(/_/g, ' ')}</span>
        <span class="tag ${o.paymentStatus === 'paid' ? 'delivered' : 'placed'}">${o.paymentMode || '—'} · ${o.paymentStatus || ''}</span></div>
        <div class="scan-total">${rupee(o.total)}${o.walletUsed ? `<div class="hint">👛 wallet -${rupee(o.walletUsed)}</div>` : ''}</div>
      </div>
      <div class="scan-cust">📱 ${o.phone}${o.address ? `<br>📍 ${o.address}` : ''}</div>
      <ul class="scan-items">${items}</ul>
      <div class="scan-actions">
        ${next ? `<button class="primary" id="scanNext">→ ${next.replace(/_/g, ' ')}</button>` : ''}
        ${o.paymentStatus === 'pending' && o.total > 0 ? `<button class="mini" id="scanPaid">💰 Mark paid</button>` : ''}
        <a class="mini slip-btn" href="/api/orders/${o.id}/slip" target="_blank">🧾 Slip</a>
      </div>
    </div>`;

  const nextBtn = document.getElementById('scanNext');
  if (nextBtn) nextBtn.addEventListener('click', async () => {
    const u = await api('/orders/' + o.id, { method: 'PATCH', body: JSON.stringify({ status: next }) });
    toast('Status → ' + next.replace(/_/g, ' '));
    renderScanOrder(u);
  });
  const paidBtn = document.getElementById('scanPaid');
  if (paidBtn) paidBtn.addEventListener('click', async () => {
    const u = await api('/orders/' + o.id, { method: 'PATCH', body: JSON.stringify({ payment_status: 'paid' }) });
    toast('💰 Marked paid');
    renderScanOrder(u);
  });
}

$('#scanForm').addEventListener('submit', (e) => {
  e.preventDefault();
  scanLookup($('#scanInput').value);
});

// camera scanning via the browser's BarcodeDetector (Chrome/Edge)
let scanStream = null;
$('#scanCamBtn').addEventListener('click', async () => {
  const video = $('#scanVideo');
  if (scanStream) { stopCamera(); return; }
  if (!('BarcodeDetector' in window)) {
    toast('⚠️ Camera scanning needs Chrome/Edge — use a USB scanner or type the code');
    return;
  }
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
  } catch {
    toast('⚠️ Camera permission denied');
    return;
  }
  video.srcObject = scanStream;
  video.style.display = 'block';
  $('#scanCamBtn').textContent = '⏹ Stop';
  await video.play();
  const detector = new BarcodeDetector({ formats: ['code_128'] });
  const tick = async () => {
    if (!scanStream) return;
    try {
      const codes = await detector.detect(video);
      if (codes.length) {
        stopCamera();
        scanLookup(codes[0].rawValue);
        return;
      }
    } catch { /* keep trying */ }
    requestAnimationFrame(tick);
  };
  tick();
});
function stopCamera() {
  if (scanStream) scanStream.getTracks().forEach((t) => t.stop());
  scanStream = null;
  $('#scanVideo').style.display = 'none';
  $('#scanCamBtn').textContent = '📷 Camera';
}

// --- WhatsApp simulator -----------------------------------------------------
const PHONE = '919800000001';
const md = (t) => t.replace(/\*(.+?)\*/g, '<b>$1</b>');

function pushMsg(text, who, extras = {}) {
  const div = document.createElement('div');
  div.className = 'msg ' + who;
  div.innerHTML = md(text);

  // tappable product list (WhatsApp interactive list message)
  if (extras.menu && extras.menu.length) {
    const list = document.createElement('div');
    list.className = 'wa-list';
    let lastSection = null;
    for (const row of extras.menu) {
      const section = row.section || null;
      if (section && section !== lastSection) {
        lastSection = section;
        const head = document.createElement('div');
        head.className = 'wa-section';
        head.textContent = section;
        list.appendChild(head);
      }
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'wa-row';
      const isCategory = row.id.length > 2; // items use letter ids (A, B, …)
      item.innerHTML = `<span class="wa-letter">${isCategory ? '🛍' : row.id}</span>
        <span class="wa-body"><span class="wa-title">${isCategory ? row.title.replace(/^🛍️\s*/, '') : row.title}</span>
        <span class="wa-desc">${row.description || ''}</span></span>
        <span class="wa-add">${isCategory ? '›' : '+'}</span>`;
      item.addEventListener('click', () => sendChat(row.id));
      list.appendChild(item);
    }
    div.appendChild(list);
  }

  // quick-reply buttons (WhatsApp reply buttons)
  if (extras.buttons && extras.buttons.length) {
    const bar = document.createElement('div');
    bar.className = 'wa-buttons';
    for (const b of extras.buttons) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'wa-btn';
      btn.textContent = b;
      btn.addEventListener('click', () => sendChat(b));
      bar.appendChild(btn);
    }
    div.appendChild(bar);
  }

  $('#chat').appendChild(div);
  $('#chat').scrollTop = $('#chat').scrollHeight;
}

async function sendChat(text) {
  text = String(text).trim();
  if (!text) return;
  // retire state-dependent quick replies; keep lists tappable like real WhatsApp
  document.querySelectorAll('.wa-buttons').forEach((el) => el.remove());
  pushMsg(text, 'me');
  try {
    const r = await api('/whatsapp/simulate', { method: 'POST', body: JSON.stringify({ phone: PHONE, message: text }) });
    pushMsg(r.reply, 'bot', { buttons: r.buttons, menu: r.menu });
    if (/order placed/i.test(r.reply)) toast('🎉 New order received!');
  } catch (err) {
    pushMsg('⚠️ ' + err.message, 'bot');
  }
}

$('#chatForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = $('#chatText').value;
  $('#chatText').value = '';
  sendChat(text);
});

// greeting with a tappable start button
pushMsg('👋 Welcome to *HSFOODS*!', 'bot', { buttons: ['menu'] });

// live admin replies: poll this phone's history and surface new admin messages
const seenAdminMsgs = new Set();
let adminPollPrimed = false;
setInterval(async () => {
  if (currentView() !== 'bot') return;
  try {
    const h = await api('/chats/' + PHONE);
    const admin = h.messages.filter((m) => m.source === 'admin');
    for (const m of admin) {
      if (!adminPollPrimed) { seenAdminMsgs.add(m.id); continue; } // skip history on first pass
      if (!seenAdminMsgs.has(m.id)) {
        seenAdminMsgs.add(m.id);
        pushMsg('👨‍💼 *HSFOODS:* ' + m.text, 'bot');
      }
    }
    adminPollPrimed = true;
  } catch { /* server restarting — ignore */ }
}, 4000);

// initial load
render('dashboard');
