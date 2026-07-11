var state = {
 chamber: '',
 committee: '',
 days: '30',
 limit: '120'
};

function byId(id) {
 return document.getElementById(id);
}

function fetchJson(url) {
 return fetch(url).then(function (res) {
 if (!res.ok) {
 throw new Error('Request failed: ' + res.status);
 }
 return res.json();
 });
}

function setMetric(id, value) {
 byId(id).textContent = value || '0';
}

function loadStats() {
 return fetchJson('/api/stats').then(function (data) {
 setMetric('totalItems', String(data.total_items || 0));
 setMetric('todayItems', String(data.today_items || 0));
 byId('lastUpdate').textContent = data.last_update || '-';
 });
}

function buildCommitteeLabel(item) {
 if (item.chamber) {
 return item.chamber + ' / ' + item.committee_name;
 }
 return item.committee_name;
}

function renderCommitteeBars(items) {
 var box = byId('committeeBars');
 box.innerHTML = '';
 if (!items || items.length === 0) {
 box.textContent = 'No committee data yet. Click Refresh Source.';
 return;
 }

 var maxCount = items[0].cnt || 1;
 if (maxCount < 1) {
 maxCount = 1;
 }

 items.slice(0, 20).forEach(function (item) {
 var row = document.createElement('div');
 row.className = 'bar-row';

 var head = document.createElement('div');
 head.className = 'bar-header';

 var left = document.createElement('span');
 left.textContent = buildCommitteeLabel(item);
 var right = document.createElement('span');
 right.textContent = String(item.cnt);

 head.appendChild(left);
 head.appendChild(right);

 var track = document.createElement('div');
 track.className = 'bar-track';

 var fill = document.createElement('div');
 fill.className = 'bar-fill';
 fill.style.width = String(Math.round((item.cnt / maxCount) * 100)) + '%';

 track.appendChild(fill);
 row.appendChild(head);
 row.appendChild(track);
 box.appendChild(row);
 });
}

function loadCommittees() {
 var query = '/api/committees?limit=80';
 if (state.chamber) {
 query = query + '&chamber=' + encodeURIComponent(state.chamber);
 }

 return fetchJson(query).then(function (data) {
 var items = data.items || [];
 renderCommitteeBars(items);

 var select = byId('committeeSelect');
 var previous = state.committee;
 select.innerHTML = '<option value=\'\'>All</option>';

 items.forEach(function (item) {
 var option = document.createElement('option');
 option.value = item.committee_slug;
 option.textContent = buildCommitteeLabel(item);
 select.appendChild(option);
 });

 if (previous) {
 select.value = previous;
 }
 });
}

function renderItems(items) {
 var body = byId('itemsTable').querySelector('tbody');
 body.innerHTML = '';

 if (!items || items.length === 0) {
 var tr = document.createElement('tr');
 var td = document.createElement('td');
 td.colSpan = 5;
 td.textContent = 'No items for current filter.';
 tr.appendChild(td);
 body.appendChild(tr);
 return;
 }

 items.forEach(function (item) {
 var tr = document.createElement('tr');

 var tdDate = document.createElement('td');
 tdDate.textContent = item.sort_date || item.display_date || '-';
 tr.appendChild(tdDate);

 var tdChamber = document.createElement('td');
 tdChamber.textContent = item.chamber || '-';
 tr.appendChild(tdChamber);

 var tdCommittee = document.createElement('td');
 tdCommittee.textContent = item.committee_cn || item.committee_en || item.committee_slug || '-';
 tr.appendChild(tdCommittee);

 var tdCategory = document.createElement('td');
 tdCategory.textContent = item.category || '-';
 tr.appendChild(tdCategory);

 var tdTitle = document.createElement('td');
 if (item.link) {
 var a = document.createElement('a');
 a.href = item.link;
 a.target = '_blank';
 a.rel = 'noreferrer';
 a.textContent = item.title || '(No title)';
 tdTitle.appendChild(a);
 } else {
 tdTitle.textContent = item.title || '(No title)';
 }
 tr.appendChild(tdTitle);

 body.appendChild(tr);
 });
}

function loadItems() {
 var query = '/api/items?days=' + encodeURIComponent(state.days) + '&limit=' + encodeURIComponent(state.limit);
 if (state.chamber) {
 query = query + '&chamber=' + encodeURIComponent(state.chamber);
 }
 if (state.committee) {
 query = query + '&committee=' + encodeURIComponent(state.committee);
 }
 return fetchJson(query).then(function (data) {
 renderItems(data.items || []);
 });
}

function refreshAll() {
 return loadStats().then(function () {
 return loadCommittees();
 }).then(function () {
 return loadItems();
 }).catch(function (err) {
 alert('Load failed: ' + err.message);
 });
}

function wireEvents() {
 byId('chamberSelect').addEventListener('change', function (e) {
 state.chamber = e.target.value;
 state.committee = '';
 byId('committeeSelect').value = '';
 loadCommittees().then(loadItems);
 });

 byId('committeeSelect').addEventListener('change', function (e) {
 state.committee = e.target.value;
 loadItems();
 });

 byId('daysSelect').addEventListener('change', function (e) {
 state.days = e.target.value;
 loadItems();
 });

 byId('refreshBtn').addEventListener('click', function () {
 var btn = byId('refreshBtn');
 btn.disabled = true;
 btn.textContent = 'Refreshing...';
 fetchJson('/api/refresh?target=all')
 .then(function () { return refreshAll(); })
 .catch(function (err) { alert('Refresh failed: ' + err.message); })
 .finally(function () {
 btn.disabled = false;
 btn.textContent = 'Refresh Source';
 });
 });
}

wireEvents();
refreshAll();
