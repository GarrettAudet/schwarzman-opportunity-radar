(function () {
  const seedUrlInput = document.getElementById('seedUrl');
  const maxPagesInput = document.getElementById('maxPages');
  const delayMsInput = document.getElementById('delayMs');
  const scopeModeInput = document.getElementById('scopeMode');
  const scanMethodInput = document.getElementById('scanMethod');
  const urlPrefixInput = document.getElementById('urlPrefix');
  const prefixField = document.getElementById('prefixField');
  const useActiveTabBtn = document.getElementById('useActiveTabBtn');
  const scanBtn = document.getElementById('scanBtn');
  const stopBtn = document.getElementById('stopBtn');
  const exportCsvBtn = document.getElementById('exportCsvBtn');
  const exportJsonBtn = document.getElementById('exportJsonBtn');
  const saveCorpusBtn = document.getElementById('saveCorpusBtn');
  const clearBtn = document.getElementById('clearBtn');
  const filterInput = document.getElementById('filterInput');
  const activeTabText = document.getElementById('activeTabText');
  const statusPill = document.getElementById('statusPill');
  const pagesCount = document.getElementById('pagesCount');
  const resourcesCount = document.getElementById('resourcesCount');
  const queuedCount = document.getElementById('queuedCount');
  const auditSummary = document.getElementById('auditSummary');
  const activityLog = document.getElementById('activityLog');
  const resourceList = document.getElementById('resourceList');

  const STORE_KEY = 'blackboard_inventory_state';
  const FILE_RE = /\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|tar|gz|mp4|avi|mov|webm|mp3|wav|ogg|png|jpe?g|gif|svg|bmp|csv|txt)($|\?)/i;
  const RENDER_SETTLE_MS = 1600;

  const state = {
    running: false,
    aborted: false,
    savingCorpus: false,
    corpusProgress: '',
    seedUrl: '',
    host: '',
    origin: '',
    scopeMode: 'host',
    scanMethod: 'fetch',
    urlPrefix: '',
    activeTabId: null,
    pagesVisited: 0,
    queue: [],
    visited: new Set(),
    resources: new Map(),
    pageLog: [],
    activity: []
  };

  init();

  async function init() {
    await restoreState();
    await useActiveTab(false);
    wireEvents();
    render();
  }

  function wireEvents() {
    useActiveTabBtn.addEventListener('click', () => useActiveTab(true));
    scopeModeInput.addEventListener('change', () => {
      if (scopeModeInput.value === 'prefix' && !urlPrefixInput.value.trim()) {
        urlPrefixInput.value = defaultPrefix(seedUrlInput.value.trim());
      }
      renderScope();
    });
    scanBtn.addEventListener('click', startScan);
    stopBtn.addEventListener('click', () => {
      state.aborted = true;
      setStatus('Stopping...', 'warning');
    });
    exportCsvBtn.addEventListener('click', exportCsv);
    exportJsonBtn.addEventListener('click', exportJson);
    saveCorpusBtn.addEventListener('click', saveCorpus);
    clearBtn.addEventListener('click', clearInventory);
    filterInput.addEventListener('input', renderResources);
  }

  async function useActiveTab(overwrite) {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.url || !/^https?:\/\//i.test(tab.url)) {
        activeTabText.textContent = 'Open a Blackboard page in this window, then click Use Active Tab.';
        return;
      }
      activeTabText.textContent = tab.title ? `Active tab: ${tab.title}` : 'Active tab detected.';
      if (overwrite || !seedUrlInput.value) {
        seedUrlInput.value = tab.url;
        state.activeTabId = tab.id;
        if (scopeModeInput.value === 'prefix') {
          urlPrefixInput.value = defaultPrefix(tab.url);
        }
      }
    } catch {
      activeTabText.textContent = 'Could not read the active tab.';
    }
  }

  async function startScan() {
    if (state.running) return;

    const seedUrl = seedUrlInput.value.trim();
    let parsed;
    try {
      parsed = new URL(seedUrl);
    } catch {
      log('Enter a valid Blackboard URL first.');
      return;
    }

    resetRun(seedUrl, parsed);
    render();
    await persistState();

    const maxPages = clampInt(maxPagesInput.value, 1, 10000, 1500);
    const delayMs = clampInt(delayMsInput.value, 0, 5000, 150);
    state.scopeMode = scopeModeInput.value === 'prefix' ? 'prefix' : 'host';
    state.scanMethod = scanMethodInput.value === 'rendered' ? 'rendered' : 'fetch';
    state.urlPrefix = state.scopeMode === 'prefix'
      ? normalizePrefix(urlPrefixInput.value.trim() || seedUrl)
      : '';
    if (state.scanMethod === 'rendered') {
      await captureActiveTabId();
      if (!state.activeTabId) {
        log('Rendered scan needs an active tab. Click Use Active Tab first.');
        state.running = false;
        render();
        return;
      }
    }

    log(state.scopeMode === 'prefix'
      ? `Starting ${state.scanMethod} prefix crawl on ${state.urlPrefix}`
      : `Starting ${state.scanMethod} host crawl on ${state.host}`);
    setStatus('Scanning', 'running');

    try {
      while (state.queue.length && state.pagesVisited < maxPages && !state.aborted) {
        const url = state.queue.shift();
        const normalized = normalizeUrl(url);
        if (!normalized || state.visited.has(normalized)) continue;
        state.visited.add(normalized);

        if (state.scanMethod === 'rendered') {
          await scanRenderedPage(normalized);
        } else {
          await scanPage(normalized);
        }
        state.pagesVisited++;
        render();

        if (state.pagesVisited % 10 === 0) await persistState();
        if (delayMs > 0 && state.queue.length && !state.aborted) {
          await sleep(delayMs);
        }
      }
      log(state.aborted ? 'Scan stopped.' : 'Scan complete.');
    } catch (err) {
      log(`Scan error: ${err.message}`);
    } finally {
      state.running = false;
      state.aborted = false;
      setStatus('Idle');
      render();
      await persistState();
    }
  }

  function resetRun(seedUrl, parsed) {
    state.running = true;
    state.aborted = false;
    state.seedUrl = seedUrl;
    state.host = parsed.host;
    state.origin = parsed.origin;
    state.scopeMode = scopeModeInput.value === 'prefix' ? 'prefix' : 'host';
    state.scanMethod = scanMethodInput.value === 'rendered' ? 'rendered' : 'fetch';
    state.urlPrefix = state.scopeMode === 'prefix'
      ? normalizePrefix(urlPrefixInput.value.trim() || seedUrl)
      : '';
    state.pagesVisited = 0;
    state.queue = [normalizeUrl(seedUrl)];
    state.visited = new Set();
    state.resources = new Map();
    state.pageLog = [];
    state.activity = [];
  }

  async function captureActiveTabId() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tab?.id && tab?.url && isSameHost(tab.url)) {
        state.activeTabId = tab.id;
      }
    } catch {
      state.activeTabId = null;
    }
  }

  async function scanPage(url) {
    log(`Fetching ${shortUrl(url)}`);
    let response;
    try {
      response = await fetch(url, { credentials: 'include', redirect: 'follow' });
    } catch (err) {
      log(`Fetch failed: ${shortUrl(url)} (${err.message})`);
      return;
    }

    const contentType = response.headers.get('content-type') || '';
    const finalUrl = normalizeUrl(response.url || url);

    if (!response.ok) {
      log(`Skipped ${response.status}: ${shortUrl(finalUrl || url)}`);
      return;
    }
    if (!contentType.includes('text/html')) {
      addResource({
        title: filenameFromUrl(finalUrl || url),
        url: finalUrl || url,
        type: detectType(finalUrl || url, ''),
        section: '',
        description: contentType,
        source_page: url,
        source_title: ''
      });
      return;
    }

    const html = await response.text();
    const parsed = parsePage(html, finalUrl || url);
    if (parsed.loginLike) {
      log(`Login page detected: ${shortUrl(finalUrl || url)}`);
      return;
    }

    state.pageLog.push({
      url: finalUrl || url,
      title: parsed.title,
      breadcrumb: parsed.breadcrumb,
      resourceCount: parsed.resources.length,
      scannedAt: new Date().toISOString()
    });

    for (const resource of parsed.resources) addResource(resource);
    for (const link of parsed.links) enqueue(link);
  }

  async function scanRenderedPage(url) {
    log(`Rendering ${shortUrl(url)}`);
    try {
      await chrome.tabs.update(state.activeTabId, { url });
      await waitForTabLoad(state.activeTabId);
      await sleep(RENDER_SETTLE_MS);
    } catch (err) {
      log(`Navigation failed: ${shortUrl(url)} (${err.message})`);
      return;
    }

    let injected;
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: state.activeTabId },
        func: extractRenderedInventoryFromPage
      });
      injected = results?.[0]?.result;
    } catch (err) {
      log(`Rendered extraction failed: ${err.message}`);
      return;
    }

    if (!injected) {
      log(`No rendered data returned from ${shortUrl(url)}`);
      return;
    }

    const pageUrl = normalizeUrl(injected.url || url) || url;
    const pageEntry = {
      url: pageUrl,
      title: injected.title || pageUrl,
      breadcrumb: injected.breadcrumb || '',
      resourceCount: injected.resources?.length || 0,
      candidateResources: injected.resources?.length || 0,
      addedResources: 0,
      duplicateResources: 0,
      filteredResources: 0,
      invalidResources: 0,
      queuedLinks: 0,
      candidateSample: (injected.resources || []).slice(0, 60).map(sampleRenderedCandidate),
      filteredSample: [],
      scannedAt: new Date().toISOString(),
      method: 'rendered'
    };

    for (const resource of injected.resources || []) {
      const normalized = normalizeResourceUrl(resource.url);
      if (!normalized) {
        pageEntry.invalidResources++;
        continue;
      }
      if (!isResourceAllowed(normalized, resource)) {
        pageEntry.filteredResources++;
        if (pageEntry.filteredSample.length < 20) {
          pageEntry.filteredSample.push(sampleRenderedCandidate(resource));
        }
        continue;
      }
      const added = addResource({
        title: resource.title,
        url: normalized,
        type: detectType(normalized, resource.title || resource.typeHint || ''),
        section: resource.section || injected.breadcrumb || injected.title || '',
        description: resource.description || '',
        source_page: pageUrl,
        source_title: injected.title || ''
      });
      if (added) pageEntry.addedResources++;
      else pageEntry.duplicateResources++;
      if (!isFileUrl(normalized) && isCrawlAllowed(normalized) && enqueue(normalized)) {
        pageEntry.queuedLinks++;
      }
    }

    for (const link of injected.links || []) {
      if (enqueue(link)) pageEntry.queuedLinks++;
    }

    state.pageLog.push(pageEntry);
  }

  function parsePage(html, pageUrl) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const title = cleanText(
      doc.querySelector('#pageTitleText, .page-title, #pageTitleBar span, h1')?.textContent ||
      doc.title ||
      pageUrl
    ).slice(0, 200);
    const breadcrumb = Array.from(
      doc.querySelectorAll('#breadcrumbs a, .path-text, .breadcrumb a, #pageTitleBar .path a')
    ).map(el => cleanText(el.textContent)).filter(Boolean).join(' > ');
    const loginLike =
      !!doc.querySelector('#loginBox, input[name="user_id"], input[type="password"]') ||
      /login|sign in|single sign-on/i.test(doc.title || '');

    const resources = [];
    const links = [];
    const seen = new Set();
    const fallbackSection = breadcrumb || title;

    for (const frame of doc.querySelectorAll('frame[src], iframe[src]')) {
      const href = absolutize(frame.getAttribute('src'), pageUrl);
      if (href && isCrawlAllowed(href)) links.push(href);
    }

    for (const a of doc.querySelectorAll('a[href]')) {
      const href = absolutize(a.getAttribute('href'), pageUrl);
      if (!href || !isSameHost(href) || seen.has(href)) continue;
      seen.add(href);
      if (!isResourceAllowed(href)) continue;

      const text = cleanText(a.textContent || a.getAttribute('title') || a.getAttribute('aria-label') || '');
      if (!isUsefulAnchor(text, href)) continue;

      const resource = {
        title: text.slice(0, 200) || filenameFromUrl(href),
        url: normalizeUrl(href),
        type: detectType(href, text),
        section: findSection(a, fallbackSection),
        description: nearbyText(a),
        source_page: pageUrl,
        source_title: title
      };
      resources.push(resource);

      if (!isFileUrl(href) && isCrawlAllowed(href)) links.push(href);
    }

    for (const item of doc.querySelectorAll('.contentListItem, .liItem, .read, .unread')) {
      const a = item.querySelector('a[href]');
      if (!a) continue;
      const href = absolutize(a.getAttribute('href'), pageUrl);
      if (!href || !isSameHost(href) || seen.has(href)) continue;
      seen.add(href);
      if (!isResourceAllowed(href)) continue;

      const text = cleanText(a.textContent || '');
      const details = cleanText(
        item.querySelector('.details, .contextItemDetailsHeaders, .vtbegenerated')?.textContent || ''
      );
      resources.push({
        title: text.slice(0, 200) || filenameFromUrl(href),
        url: normalizeUrl(href),
        type: detectType(href, text),
        section: findSection(a, fallbackSection),
        description: details.slice(0, 240),
        source_page: pageUrl,
        source_title: title
      });

      if (!isFileUrl(href) && isCrawlAllowed(href)) links.push(href);
    }

    return { title, breadcrumb, loginLike, resources, links };
  }

  function addResource(resource) {
    if (!resource.url) return false;
    const id = resourceId(resource.url);
    const existing = state.resources.get(id);
    const isNew = !existing;
    const normalizedUrl = normalizeResourceUrl(resource.url) || resource.url;
    const next = {
      id,
      title: resource.title || existing?.title || 'Untitled',
      url: normalizedUrl,
      type: resource.type || existing?.type || 'link',
      section: resource.section || existing?.section || '',
      description: resource.description || existing?.description || '',
      source_page: shouldPreserveExistingSource(existing, resource)
        ? existing.source_page
        : (resource.source_page || existing?.source_page || ''),
      source_title: shouldPreserveExistingSource(existing, resource)
        ? existing.source_title
        : (resource.source_title || existing?.source_title || ''),
      external: isExternalUrl(normalizedUrl),
      seen_at: existing?.seen_at || new Date().toISOString()
    };
    state.resources.set(id, next);
    return isNew;
  }

  function enqueue(url) {
    const normalized = normalizeUrl(url);
    if (!normalized) return false;
    if (!isCrawlAllowed(normalized)) return false;
    if (state.visited.has(normalized)) return false;
    if (state.queue.includes(normalized)) return false;
    state.queue.push(normalized);
    return true;
  }

  function normalizeUrl(url) {
    try {
      const u = new URL(url);
      if (state.host && u.host !== state.host) return null;
      u.hash = '';
      for (const key of [
        'nonce',
        'timestamp',
        'uniqueid',
        'lti_msg',
        'lti_errormsg',
        'new_loc',
        'session',
        'JSESSIONID'
      ]) {
        u.searchParams.delete(key);
      }
      u.searchParams.sort();
      return u.toString();
    } catch {
      return null;
    }
  }

  function normalizeResourceUrl(url) {
    try {
      const u = new URL(url);
      u.hash = '';
      for (const key of [
        'nonce',
        'timestamp',
        'uniqueid',
        'lti_msg',
        'lti_errormsg',
        'new_loc',
        'session',
        'JSESSIONID'
      ]) {
        u.searchParams.delete(key);
      }
      u.searchParams.sort();
      return u.toString();
    } catch {
      return null;
    }
  }

  function absolutize(raw, base) {
    if (!raw) return null;
    if (/^(javascript:|mailto:|tel:|#)/i.test(raw.trim())) return null;
    try {
      return new URL(raw, base).toString();
    } catch {
      return null;
    }
  }

  function isSameHost(url) {
    try {
      return new URL(url).host === state.host;
    } catch {
      return false;
    }
  }

  function isCrawlAllowed(url) {
    if (!isSameHost(url)) return false;
    if (!isCrawlable(url)) return false;
    if (state.scopeMode !== 'prefix') return true;
    return isWithinPrefix(url);
  }

  function isResourceAllowed(url, resource = {}) {
    if (isExternalUrl(url)) {
      return !!resource.contentLink && !isNoisyExternalUrl(url);
    }
    if (!isSameHost(url)) return false;
    if (resource.contentLink && isDownloadResourceUrl(url)) return true;
    if (state.scopeMode !== 'prefix') return true;
    return isWithinPrefix(url) || isFileUrl(url);
  }

  function isExternalUrl(url) {
    try {
      return !!state.host && new URL(url).host !== state.host;
    } catch {
      return false;
    }
  }

  function isNoisyExternalUrl(url) {
    return /(?:12twenty|intercom|segment|sentry|google-analytics|googletagmanager|facebook|twitter|linkedin\.com\/share)/i.test(url);
  }

  function isDownloadResourceUrl(url) {
    try {
      const u = new URL(url);
      return /\/api\/v\d+\/resource-library-items\/\d+\/download\/?$/i.test(u.pathname);
    } catch {
      return false;
    }
  }

  function isWithinPrefix(url) {
    try {
      const prefix = new URL(state.urlPrefix);
      const candidate = new URL(url);
      if (candidate.origin !== prefix.origin) return false;
      const prefixPath = trimTrailingSlash(prefix.pathname || '/');
      const candidatePath = trimTrailingSlash(candidate.pathname || '/');
      if (candidatePath === prefixPath) return true;
      if (candidatePath.startsWith(`${prefixPath}/`)) return true;
      const normalized = normalizeUrl(url) || url;
      return normalized.startsWith(state.urlPrefix);
    } catch {
      return false;
    }
  }

  function isFileUrl(url) {
    return FILE_RE.test(url) || /bbcswebdav|@X@/i.test(url);
  }

  function isCrawlable(url) {
    const lower = url.toLowerCase();
    if (!/^https?:\/\//.test(lower)) return false;
    if (isFileUrl(url)) return false;
    if (/logout|logoff|signout/.test(lower)) return false;
    if (/\/webapps\/login/.test(lower)) return false;
    if (/\/webapps\/gradebook\//.test(lower)) return false;
    if (/\/api\//.test(lower) || /\.json($|\?)/.test(lower)) return false;
    if (/action=(delete|remove|toggleavailability|gradeattempt|submit|upload)/.test(lower)) return false;
    if (/cmd=(delete|remove|grade|submit|upload)/.test(lower)) return false;
    if (/do(action|upload|submit|delete)/i.test(url)) return false;
    if (/assessment|takequiz|taketest|attempt/i.test(url)) return false;
    return true;
  }

  function isUsefulAnchor(text, href) {
    const lowerText = text.toLowerCase();
    if (!text && !isFileUrl(href)) return false;
    if (/^(ok|yes|no|cancel|close|help|skip|next|previous|back|home|menu)$/i.test(text)) return false;
    if (/log\s?out|sign\s?out/.test(lowerText)) return false;
    return true;
  }

  function detectType(url, text) {
    const lower = `${url} ${text}`.toLowerCase();
    if (/\.pdf($|\?)/.test(lower)) return 'pdf';
    if (/\.(docx?|rtf)($|\?)/.test(lower)) return 'document';
    if (/\.(xlsx?|csv)($|\?)/.test(lower)) return 'spreadsheet';
    if (/\.pptx?($|\?)/.test(lower)) return 'presentation';
    if (/\.(zip|rar|7z|tar|gz)($|\?)/.test(lower)) return 'archive';
    if (/\.(mp4|avi|mov|webm)($|\?)/.test(lower)) return 'video';
    if (/\.(mp3|wav|ogg)($|\?)/.test(lower)) return 'audio';
    if (/\.(png|jpe?g|gif|svg|bmp)($|\?)/.test(lower)) return 'image';
    if (/\bfolder\b/.test(lower)) return 'folder';
    if (/\/api\/v\d+\/resource-library-items\/\d+\/download/.test(lower)) return 'download';
    if (/announcement/.test(lower)) return 'announcement';
    if (/course/.test(lower) && /id/.test(lower)) return 'course';
    return 'link';
  }

  function findSection(el, fallback) {
    let node = el.parentElement;
    for (let i = 0; i < 10 && node; i++) {
      const heading = node.querySelector('h2, h3, h4, .sectionTitle, .item-title');
      if (heading) {
        const text = cleanText(heading.textContent);
        if (text && text.length < 120) return text;
      }
      const prev = node.previousElementSibling;
      if (prev && /^h[2-4]$/i.test(prev.tagName)) {
        return cleanText(prev.textContent).slice(0, 120);
      }
      node = node.parentElement;
    }
    return fallback || '';
  }

  function nearbyText(el) {
    const title = cleanText(el.getAttribute('title') || el.getAttribute('aria-label') || '');
    if (title) return title.slice(0, 240);
    const parent = el.closest('li, div, td, .item, .contentListItem');
    if (!parent) return '';
    const text = cleanText(parent.textContent).slice(0, 240);
    const linkText = cleanText(el.textContent);
    if (text.length > linkText.length + 10) return text;
    return '';
  }

  function resourceId(url) {
    const normalized = normalizeResourceUrl(url) || url;
    let hash = 0;
    for (let i = 0; i < normalized.length; i++) {
      hash = ((hash << 5) - hash + normalized.charCodeAt(i)) | 0;
    }
    return `r_${Math.abs(hash).toString(36)}`;
  }

  function shouldPreserveExistingSource(existing, incoming) {
    if (!existing) return false;
    const existingLooksBreadcrumb = looksLikeBreadcrumb(existing.description || '');
    const incomingLooksBreadcrumb = looksLikeBreadcrumb(incoming.description || '');
    if (!existingLooksBreadcrumb && incomingLooksBreadcrumb) return true;
    if (existingLooksBreadcrumb && !incomingLooksBreadcrumb) return false;
    return false;
  }

  function looksLikeBreadcrumb(text) {
    return /^home\s*>/i.test(text || '');
  }

  function render() {
    pagesCount.textContent = String(state.pagesVisited);
    resourcesCount.textContent = String(state.resources.size);
    queuedCount.textContent = String(state.queue.length);
    scanBtn.disabled = state.running;
    stopBtn.disabled = !state.running;
    exportCsvBtn.disabled = state.resources.size === 0;
    exportJsonBtn.disabled = state.resources.size === 0;
    saveCorpusBtn.disabled = state.resources.size === 0 || state.savingCorpus;
    renderActivity();
    renderScope();
    renderAudit();
    renderResources();
  }

  function renderScope() {
    const prefixMode = scopeModeInput.value === 'prefix';
    prefixField.style.display = prefixMode ? 'grid' : 'none';
  }

  function renderActivity() {
    activityLog.innerHTML = '';
    for (const item of state.activity.slice(-20).reverse()) {
      const li = document.createElement('li');
      li.textContent = item;
      activityLog.appendChild(li);
    }
  }

  function renderAudit() {
    const summary = buildCrawlSummary();
    if (!summary.pages) {
      auditSummary.textContent = 'No scan yet.';
      return;
    }

    auditSummary.innerHTML = '';
    for (const line of [
      ['Rendered candidates', summary.candidateResources],
      ['Added resources', summary.addedResources],
      ['Duplicates', summary.duplicateResources],
      ['Filtered', summary.filteredResources],
      ['Queued child pages', summary.queuedLinks]
    ]) {
      const row = document.createElement('div');
      row.innerHTML = `<strong>${line[1]}</strong> ${line[0].toLowerCase()}`;
      auditSummary.appendChild(row);
    }
    if (state.corpusProgress) {
      const row = document.createElement('div');
      row.className = 'progress';
      row.textContent = state.corpusProgress;
      auditSummary.appendChild(row);
    }
  }

  function renderResources() {
    const filter = filterInput.value.trim().toLowerCase();
    const resources = Array.from(state.resources.values())
      .sort((a, b) => (a.section || '').localeCompare(b.section || '') || (a.title || '').localeCompare(b.title || ''))
      .filter(r => !filter || [
        r.title,
        r.type,
        r.section,
        r.description,
        r.source_title,
        r.url
      ].join(' ').toLowerCase().includes(filter))
      .slice(0, 300);

    if (resources.length === 0) {
      resourceList.className = 'resource-list empty';
      resourceList.textContent = state.resources.size ? 'No resources match the filter.' : 'No resources yet.';
      return;
    }

    resourceList.className = 'resource-list';
    resourceList.innerHTML = '';
    for (const resource of resources) {
      const card = document.createElement('article');
      card.className = 'resource';

      const title = document.createElement('div');
      title.className = 'resource-title';
      title.append(document.createTextNode(resource.title || 'Untitled'));

      const type = document.createElement('span');
      type.className = 'resource-type';
      type.textContent = resource.type || 'link';
      title.appendChild(type);

      const meta = document.createElement('div');
      meta.className = 'resource-meta';
      meta.textContent = [resource.section, resource.source_title].filter(Boolean).join(' | ');

      const link = document.createElement('a');
      link.href = resource.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = resource.url;

      card.append(title, meta, link);
      resourceList.appendChild(card);
    }
  }

  function setStatus(text, mode) {
    statusPill.textContent = text;
    statusPill.className = `pill${mode ? ` ${mode}` : ''}`;
  }

  function log(message) {
    const stamped = `${new Date().toLocaleTimeString()} - ${message}`;
    state.activity.push(stamped);
    if (state.activity.length > 200) state.activity = state.activity.slice(-200);
  }

  async function clearInventory() {
    if (state.running) return;
    state.seedUrl = '';
    state.host = '';
    state.origin = '';
    state.scopeMode = 'host';
    state.scanMethod = 'fetch';
    state.urlPrefix = '';
    state.activeTabId = null;
    state.pagesVisited = 0;
    state.queue = [];
    state.visited = new Set();
    state.resources = new Map();
    state.pageLog = [];
    state.activity = [];
    setStatus('Idle');
    render();
    await chrome.storage.local.remove(STORE_KEY);
  }

  async function persistState() {
    const payload = {
      seedUrl: state.seedUrl,
      host: state.host,
      origin: state.origin,
      scopeMode: state.scopeMode,
      scanMethod: state.scanMethod,
      urlPrefix: state.urlPrefix,
      activeTabId: state.activeTabId,
      pagesVisited: state.pagesVisited,
      queue: state.queue,
      visited: Array.from(state.visited),
      resources: Array.from(state.resources.values()),
      pageLog: state.pageLog,
      activity: state.activity
    };
    await chrome.storage.local.set({ [STORE_KEY]: payload });
  }

  async function restoreState() {
    try {
      const stored = await chrome.storage.local.get(STORE_KEY);
      const payload = stored[STORE_KEY];
      if (!payload) return;
      state.seedUrl = payload.seedUrl || '';
      state.host = payload.host || '';
      state.origin = payload.origin || '';
      state.scopeMode = payload.scopeMode || 'host';
      state.scanMethod = payload.scanMethod || 'fetch';
      state.urlPrefix = payload.urlPrefix || '';
      state.activeTabId = payload.activeTabId || null;
      state.pagesVisited = payload.pagesVisited || 0;
      state.queue = payload.queue || [];
      state.visited = new Set(payload.visited || []);
      state.resources = new Map((payload.resources || []).map(r => [r.id, r]));
      state.pageLog = payload.pageLog || [];
      state.activity = payload.activity || [];
      seedUrlInput.value = state.seedUrl || seedUrlInput.value;
      scopeModeInput.value = state.scopeMode;
      scanMethodInput.value = state.scanMethod;
      urlPrefixInput.value = state.urlPrefix;
    } catch {
      // Ignore restore errors; a fresh scan is fine.
    }
  }

  function exportJson() {
    const payload = buildInventoryPayload();
    downloadBlob(
      JSON.stringify(payload, null, 2),
      `blackboard-inventory-${dateStamp()}.json`,
      'application/json'
    );
  }

  function buildInventoryPayload() {
    return {
      exported_at: new Date().toISOString(),
      seed_url: state.seedUrl,
      host: state.host,
      scope_mode: state.scopeMode,
      scan_method: state.scanMethod,
      url_prefix: state.urlPrefix,
      pages_visited: state.pagesVisited,
      crawl_summary: buildCrawlSummary(),
      resources: Array.from(state.resources.values()),
      pages: state.pageLog
    };
  }

  function exportCsv() {
    const rows = [
      ['id', 'title', 'type', 'section', 'description', 'url', 'external', 'source_title', 'source_page', 'seen_at'],
      ...Array.from(state.resources.values()).map(r => [
        r.id,
        r.title,
        r.type,
        r.section,
        r.description,
        r.url,
        r.external ? 'true' : 'false',
        r.source_title,
        r.source_page,
        r.seen_at
      ])
    ];
    const csv = rows.map(row => row.map(csvEscape).join(',')).join('\r\n');
    downloadBlob(csv, `blackboard-inventory-${dateStamp()}.csv`, 'text/csv');
  }

  async function saveCorpus() {
    if (!window.showDirectoryPicker) {
      log('Corpus save needs Chrome File System Access support.');
      return;
    }

    const downloads = getCorpusDownloadResources();
    if (downloads.length === 0) {
      log('No downloadable Rencai resources found. Run the rendered Rencai scan first.');
      return;
    }

    state.savingCorpus = true;
    state.corpusProgress = 'Choose the repo root folder: C:\\repos\\SchwarzmanScholarResources';
    render();

    let rootDir;
    try {
      rootDir = await window.showDirectoryPicker({ id: 'schwarzman-scholar-resources', mode: 'readwrite' });
    } catch {
      state.savingCorpus = false;
      state.corpusProgress = 'Corpus save canceled.';
      render();
      return;
    }

    if (!(await isValidCorpusRoot(rootDir))) {
      state.savingCorpus = false;
      state.corpusProgress = 'Wrong folder selected. Choose C:\\repos\\SchwarzmanScholarResources.';
      log(state.corpusProgress);
      render();
      return;
    }

    const stamp = fileTimestamp();
    const dataDir = await ensureDir(rootDir, 'data');
    const rencaiDir = await ensureDir(dataDir, 'rencai');
    const rawDir = await ensureDir(rencaiDir, 'raw');
    const manifestsDir = await ensureDir(rencaiDir, 'manifests');
    const reviewDir = await ensureDir(rencaiDir, 'review');
    await ensureDir(rencaiDir, 'text');

    const inventoryPayload = buildInventoryPayload();
    await writeTextFile(manifestsDir, `inventory-${stamp}.json`, JSON.stringify(inventoryPayload, null, 2));

    const manifestRows = [];
    const usedPaths = new Set();
    let completed = 0;
    let failed = 0;

    for (const resource of downloads) {
      completed++;
      state.corpusProgress = `Downloading ${completed}/${downloads.length}: ${resource.title}`;
      render();

      const folderParts = folderPathForResource(resource);
      const folderDir = await ensureNestedDir(rawDir, folderParts);
      const filename = uniqueFilename(
        usedPaths,
        [...folderParts, filenameForResource(resource)].join('/')
      ).split('/').pop();
      const localPath = ['data', 'rencai', 'raw', ...folderParts, filename].join('/');

      const row = {
        id: resource.id,
        title: resource.title,
        type: resource.type,
        source_page: resource.source_page,
        source_title: resource.source_title,
        url: resource.url,
        local_path: localPath,
        status: 'pending',
        content_type: '',
        bytes: 0,
        error: ''
      };

      try {
        const response = await fetch(resource.url, { credentials: 'include', redirect: 'follow' });
        row.status = String(response.status);
        row.content_type = response.headers.get('content-type') || '';
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        row.bytes = blob.size;
        await writeBlobFile(folderDir, filename, blob);
      } catch (err) {
        failed++;
        row.error = err.message || String(err);
      }

      manifestRows.push(row);
    }

    await writeTextFile(manifestsDir, `download-manifest-${stamp}.json`, JSON.stringify(manifestRows, null, 2));
    await writeTextFile(manifestsDir, `download-manifest-${stamp}.csv`, rowsToCsv([
      ['id', 'title', 'type', 'source_page', 'source_title', 'url', 'local_path', 'status', 'content_type', 'bytes', 'error'],
      ...manifestRows.map(row => [
        row.id,
        row.title,
        row.type,
        row.source_page,
        row.source_title,
        row.url,
        row.local_path,
        row.status,
        row.content_type,
        row.bytes,
        row.error
      ])
    ]));
    await writeTextFile(reviewDir, `allowlist-review-${stamp}.csv`, rowsToCsv([
      ['include', 'category', 'audience', 'sensitivity', 'notes', 'title', 'type', 'source_page', 'local_path', 'url'],
      ...manifestRows.map(row => [
        'review',
        categoryGuess(row),
        'incoming/career',
        'review',
        '',
        row.title,
        row.type,
        row.source_page,
        row.local_path,
        row.url
      ])
    ]));

    state.savingCorpus = false;
    state.corpusProgress = `Saved ${manifestRows.length - failed}/${manifestRows.length} files to data/rencai (${failed} failed).`;
    log(state.corpusProgress);
    render();
  }

  function getCorpusDownloadResources() {
    return Array.from(state.resources.values())
      .filter(resource => isDownloadResourceUrl(resource.url))
      .sort((a, b) => (a.source_page || '').localeCompare(b.source_page || '') || (a.title || '').localeCompare(b.title || ''));
  }

  async function ensureDir(parent, name) {
    return parent.getDirectoryHandle(name, { create: true });
  }

  async function isValidCorpusRoot(rootDir) {
    try {
      await rootDir.getFileHandle('manifest.json');
      await rootDir.getFileHandle('panel.js');
      const dataDir = await rootDir.getDirectoryHandle('data');
      await dataDir.getDirectoryHandle('rencai');
      return true;
    } catch {
      return false;
    }
  }

  async function ensureNestedDir(parent, parts) {
    let dir = parent;
    for (const part of parts) dir = await ensureDir(dir, part);
    return dir;
  }

  async function writeTextFile(dir, filename, text) {
    const handle = await dir.getFileHandle(filename, { create: true });
    const writable = await handle.createWritable();
    await writable.write(text);
    await writable.close();
  }

  async function writeBlobFile(dir, filename, blob) {
    const handle = await dir.getFileHandle(filename, { create: true });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
  }

  function rowsToCsv(rows) {
    return rows.map(row => row.map(csvEscape).join(',')).join('\r\n');
  }

  function folderPathForResource(resource) {
    const folders = buildFolderMaps();
    const chain = [];
    const seen = new Set();
    let current = resourceKey(resource.source_page);

    while (current && !seen.has(current)) {
      seen.add(current);
      const folder = folders.byUrl.get(current);
      if (!folder) break;
      if (folder.title && !/^resource library$/i.test(folder.title)) {
        chain.unshift(sanitizePathSegment(folder.title));
      }
      const parent = resourceKey(folder.source_page);
      if (!parent || parent === current) break;
      current = parent;
    }

    if (chain.length === 0) {
      const sourceTitle = folders.byUrl.get(resourceKey(resource.source_page))?.title || 'uncategorized';
      chain.push(sanitizePathSegment(sourceTitle));
    }
    return chain.slice(0, 6);
  }

  function buildFolderMaps() {
    const byUrl = new Map();
    for (const resource of state.resources.values()) {
      if (!resource.external && resource.url && resource.url.includes('/resource-library')) {
        byUrl.set(resourceKey(resource.url), resource);
      }
    }
    return { byUrl };
  }

  function resourceKey(url) {
    try {
      const u = new URL(url);
      u.hash = '';
      u.search = '';
      return u.toString().replace(/\/+$/, '');
    } catch {
      return '';
    }
  }

  function filenameForResource(resource) {
    const title = sanitizeFilename(resource.title || `resource-${resource.id}`);
    if (/\.[a-z0-9]{2,6}$/i.test(title)) return title;
    const extension = extensionForResource(resource);
    return `${title}${extension}`;
  }

  function extensionForResource(resource) {
    if (resource.type === 'pdf') return '.pdf';
    if (resource.type === 'document') return '.docx';
    if (resource.type === 'spreadsheet') return '.xlsx';
    if (resource.type === 'presentation') return '.pptx';
    if (resource.type === 'image') return '.png';
    return '.bin';
  }

  function sanitizePathSegment(value) {
    return sanitizeFilename(value).replace(/\.[a-z0-9]{2,6}$/i, '').slice(0, 80) || 'folder';
  }

  function sanitizeFilename(value) {
    return (value || 'file')
      .normalize('NFKD')
      .replace(/[^\w.\- ]+/g, '_')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/[. ]+$/g, '')
      .slice(0, 140) || 'file';
  }

  function uniqueFilename(usedPaths, relativePath) {
    const parts = relativePath.split('/');
    const filename = parts.pop();
    const dot = filename.lastIndexOf('.');
    const stem = dot > 0 ? filename.slice(0, dot) : filename;
    const ext = dot > 0 ? filename.slice(dot) : '';
    let candidate = [...parts, filename].join('/');
    let i = 2;
    while (usedPaths.has(candidate.toLowerCase())) {
      candidate = [...parts, `${stem} (${i})${ext}`].join('/');
      i++;
    }
    usedPaths.add(candidate.toLowerCase());
    return candidate;
  }

  function categoryGuess(row) {
    const text = `${row.title} ${row.source_page}`.toLowerCase();
    if (/resume|cover|interview|linkedin|job|career|consulting|finance|internship/.test(text)) return 'career';
    if (/visa|china|language|transcript|degree|test|gmat|gre|mcat/.test(text)) return 'pre-arrival';
    return 'resource';
  }

  function fileTimestamp() {
    return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  }

  function downloadBlob(content, filename, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function csvEscape(value) {
    const text = value == null ? '' : String(value);
    return `"${text.replace(/"/g, '""')}"`;
  }

  function buildCrawlSummary() {
    const pages = state.pageLog || [];
    return {
      pages: pages.length,
      candidateResources: sumPages('candidateResources'),
      addedResources: sumPages('addedResources'),
      duplicateResources: sumPages('duplicateResources'),
      filteredResources: sumPages('filteredResources'),
      invalidResources: sumPages('invalidResources'),
      queuedLinks: sumPages('queuedLinks')
    };
  }

  function sumPages(field) {
    return (state.pageLog || []).reduce((sum, page) => sum + Number(page[field] || 0), 0);
  }

  function sampleRenderedCandidate(resource) {
    return {
      title: resource.title || '',
      url: resource.url || '',
      description: resource.description || '',
      section: resource.section || '',
      contentLink: !!resource.contentLink,
      typeHint: resource.typeHint || ''
    };
  }

  function filenameFromUrl(url) {
    try {
      const path = decodeURIComponent(new URL(url).pathname);
      return path.split('/').filter(Boolean).pop() || url;
    } catch {
      return url;
    }
  }

  function normalizePrefix(url) {
    try {
      const u = new URL(url);
      u.hash = '';
      u.searchParams.sort();
      return u.toString();
    } catch {
      return '';
    }
  }

  function defaultPrefix(url) {
    try {
      const u = new URL(url);
      u.hash = '';
      u.search = '';
      if (!u.pathname.endsWith('/')) {
        const parts = u.pathname.split('/');
        parts.pop();
        u.pathname = `${parts.join('/')}/`;
      }
      return u.toString();
    } catch {
      return '';
    }
  }

  function trimTrailingSlash(path) {
    if (path.length > 1 && path.endsWith('/')) return path.slice(0, -1);
    return path;
  }

  function waitForTabLoad(tabId) {
    return new Promise(resolve => {
      let done = false;
      const timeout = setTimeout(finish, 12000);

      function finish() {
        if (done) return;
        done = true;
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }

      function listener(updatedTabId, changeInfo) {
        if (updatedTabId === tabId && changeInfo.status === 'complete') finish();
      }

      chrome.tabs.onUpdated.addListener(listener);
    });
  }

  function extractRenderedInventoryFromPage() {
    const clean = text => (text || '').replace(/\s+/g, ' ').trim();
    const abs = raw => {
      if (!raw || /^(javascript:|mailto:|tel:|#)/i.test(String(raw).trim())) return null;
      try {
        return new URL(raw, window.location.href).toString();
      } catch {
        return null;
      }
    };
    const nearby = el => {
      const row = el.closest('tr, li, [role="row"], [class*="row"], [class*="item"], [class*="resource"], [class*="folder"]');
      const text = clean(row?.textContent || el.closest('div')?.textContent || '');
      const own = clean(el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
      return text && text !== own ? text.slice(0, 300) : '';
    };
    const isChrome = el => !!el.closest('nav, header, footer, aside, [role="navigation"], [aria-label*="navigation" i], [class*="sidebar"], [class*="menu"], [class*="navbar"], [class*="topbar"], [class*="intercom"]');
    const isNoisyTitle = title => /^(account settings|application materials|applied|appointments|calendar|career fairs|experiences|help|home|jobs|messages|profile|resource library|sign out|students|surveys)$/i.test(title);
    const isRootLibrary = href => {
      try {
        return new URL(href).pathname.replace(/\/+$/, '') === '/resource-library';
      } catch {
        return false;
      }
    };
    const section = el => {
      let node = el.parentElement;
      for (let i = 0; i < 8 && node; i++) {
        const heading = node.querySelector('h1, h2, h3, h4, [class*="title"], [class*="breadcrumb"]');
        const text = clean(heading?.textContent || '');
        if (text && text.length < 160) return text;
        node = node.parentElement;
      }
      return clean(document.querySelector('h1, h2, [class*="breadcrumb"]')?.textContent || document.title || '');
    };

    const resources = [];
    const links = [];
    const seen = new Set();

    for (const a of document.querySelectorAll('a[href]')) {
      const href = abs(a.getAttribute('href'));
      if (!href || seen.has(href)) continue;
      seen.add(href);
      const title = clean(a.textContent || a.getAttribute('aria-label') || a.getAttribute('title') || '');
      if (!title || /^(ok|yes|no|cancel|close|help|skip|next|previous|back|home|menu)$/i.test(title)) continue;
      if (/^resource library$/i.test(title) && isRootLibrary(href)) continue;
      const contentLink = !isChrome(a) && !isNoisyTitle(title);
      if (!contentLink && !href.includes('/resource-library')) continue;
      resources.push({
        title,
        url: href,
        section: section(a),
        description: nearby(a),
        typeHint: a.closest('[class*="folder"], [data-icon*="folder"]') ? 'folder' : '',
        contentLink
      });
      links.push(href);
    }

    for (const el of document.querySelectorAll('[role="link"], [data-href], [data-url]')) {
      const href = abs(el.getAttribute('href') || el.dataset.href || el.dataset.url);
      if (!href || seen.has(href)) continue;
      seen.add(href);
      const title = clean(el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
      if (!title) continue;
      if (/^resource library$/i.test(title) && isRootLibrary(href)) continue;
      const contentLink = !isChrome(el) && !isNoisyTitle(title);
      if (!contentLink && !href.includes('/resource-library')) continue;
      resources.push({
        title,
        url: href,
        section: section(el),
        description: nearby(el),
        typeHint: 'rendered-link',
        contentLink
      });
      links.push(href);
    }

    return {
      url: window.location.href,
      title: clean(document.querySelector('h1')?.textContent || document.title || window.location.href),
      breadcrumb: clean(document.querySelector('[aria-label*="breadcrumb" i], .breadcrumb, [class*="breadcrumb"]')?.textContent || ''),
      resources,
      links
    };
  }

  function shortUrl(url) {
    try {
      const u = new URL(url);
      return `${u.pathname}${u.search}`.slice(0, 90) || u.host;
    } catch {
      return String(url).slice(0, 90);
    }
  }

  function cleanText(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  function clampInt(value, min, max, fallback) {
    const parsed = parseInt(value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function dateStamp() {
    return new Date().toISOString().slice(0, 10);
  }
})();
