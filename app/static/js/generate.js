/* R03 智能生成页交互
 * 说明：生成过程调用外部大模型，耗时受服务影响（4.1 性能需求），
 * 因此采用异步提交 + 处理状态提示，失败时给出明确原因且不写入任何数据。
 */
(function () {
  'use strict';

  var reqData = {};
  try {
    reqData = JSON.parse(document.getElementById('requirementData').textContent || '{}');
  } catch (e) { reqData = {}; }

  var sel = document.getElementById('requirementSelect');
  var countEl = document.getElementById('count');
  var extraEl = document.getElementById('extra');
  var btn = document.getElementById('genBtn');
  var statusEl = document.getElementById('genStatus');
  var previewEl = document.getElementById('reqPreview');
  var body = document.getElementById('resultBody');
  var countBadge = document.getElementById('genCount');
  var saveBtn = document.getElementById('saveBtn');
  var toggleAll = document.getElementById('toggleAll');
  var saveForm = document.getElementById('saveForm');
  var saveReqId = document.getElementById('saveRequirementId');

  var CATEGORY_OPTIONS = ['功能测试', '边界测试', '异常测试', '权限测试', '性能测试', '兼容性测试'];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function setStatus(html, type) {
    var cls = type ? 'text-' + type : 'text-muted';
    statusEl.innerHTML = '<span class="' + cls + '">' + html + '</span>';
  }

  // ---------- 需求预览 ----------
  function refreshPreview() {
    var d = reqData[sel.value];
    if (!d) {
      previewEl.innerHTML = '<span class="text-muted">选择需求后显示其描述与业务规则，作为模型生成的输入。</span>';
      saveReqId.value = '';
      return;
    }
    saveReqId.value = sel.value;
    var warn = '';
    if (!d.description || d.description.trim().length < 10) {
      warn = '<div class="alert alert-warning py-2 px-2 small mb-2">该需求描述为空或过短，'
        + '无法提交生成，请先补充需求描述。</div>';
    }
    previewEl.innerHTML = warn
      + '<div class="fw-semibold mb-1">' + esc(d.code) + ' ' + esc(d.name) + '</div>'
      + '<div class="text-secondary small mb-1">需求描述</div>'
      + '<div class="pre-wrap small mb-2">' + (esc(d.description) || '（未填写）') + '</div>'
      + '<div class="text-secondary small mb-1">业务规则</div>'
      + '<div class="pre-wrap small mb-2">' + (esc(d.business_rules) || '（未填写）') + '</div>'
      + '<div class="text-muted small">该需求下已有 ' + (d.case_count || 0) + ' 条测试用例</div>';
  }

  sel.addEventListener('change', refreshPreview);
  refreshPreview();

  // ---------- 生成结果渲染 ----------
  function priorityOptions(cur) {
    var map = { high: '高', medium: '中', low: '低' };
    return Object.keys(map).map(function (k) {
      return '<option value="' + k + '"' + (cur === k ? ' selected' : '') + '>' + map[k] + '</option>';
    }).join('');
  }

  function buildRow(idx, r) {
    var tr = document.createElement('tr');
    tr.setAttribute('data-row', idx);
    tr.innerHTML =
      '<td class="text-center"><input class="form-check-input" type="checkbox"'
      + ' name="rows-' + idx + '-selected" checked></td>'
      + '<td><input type="text" class="form-control form-control-sm" name="rows-' + idx
      + '-title" maxlength="200" value="' + esc(r.title) + '" required></td>'
      + '<td><input type="text" class="form-control form-control-sm" name="rows-' + idx
      + '-category" list="categoryOptions" value="' + esc(r.category || '功能测试') + '"></td>'
      + '<td><select class="form-select form-select-sm" name="rows-' + idx + '-priority">'
      + priorityOptions(r.priority) + '</select></td>'
      + '<td><textarea class="form-control form-control-sm" name="rows-' + idx
      + '-precondition" rows="2">' + esc(r.precondition) + '</textarea></td>'
      + '<td><textarea class="form-control form-control-sm" name="rows-' + idx
      + '-steps" rows="4">' + esc(r.steps) + '</textarea></td>'
      + '<td><textarea class="form-control form-control-sm" name="rows-' + idx
      + '-test_data" rows="2">' + esc(r.test_data) + '</textarea></td>'
      + '<td><textarea class="form-control form-control-sm" name="rows-' + idx
      + '-expected_result" rows="3">' + esc(r.expected_result) + '</textarea></td>'
      + '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-danger"'
      + ' title="移除该行"><i class="bi bi-x-lg"></i></button></td>';
    tr.querySelector('button').addEventListener('click', function () {
      tr.remove();
      renumber();
      updateCount();
    });
    return tr;
  }

  // 删除任意行后重新编号，保证服务端按 rows-0..n-1 连续读取
  function renumber() {
    Array.prototype.slice.call(body.querySelectorAll('tr[data-row]')).forEach(function (tr, i) {
      tr.setAttribute('data-row', i);
      tr.querySelectorAll('[name]').forEach(function (el) {
        el.name = el.name.replace(/^rows-\d+-/, 'rows-' + i + '-');
      });
    });
  }

  function updateCount() {
    var rows = body.querySelectorAll('tr[data-row]');
    var selected = body.querySelectorAll('input[name$="-selected"]:checked').length;
    countBadge.textContent = rows.length + ' 条（已选 ' + selected + '）';
    saveBtn.disabled = rows.length === 0;

    // 同步行数，供服务端确定扫描范围
    var hidden = document.getElementById('rowTotal');
    if (!hidden) {
      hidden = document.createElement('input');
      hidden.type = 'hidden'; hidden.id = 'rowTotal'; hidden.name = 'row_total';
      saveForm.appendChild(hidden);
    }
    hidden.value = rows.length;
    if (toggleAll) { toggleAll.disabled = rows.length === 0; }
  }

  function renderResults(items) {
    body.innerHTML = '';
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">模型未返回有效用例。</td></tr>';
      updateCount();
      return;
    }
    items.forEach(function (r, i) { body.appendChild(buildRow(i, r)); });
    updateCount();
  }

  // ---------- 提交生成 ----------
  btn.addEventListener('click', function () {
    var reqId = sel.value;
    if (!reqId) {
      setStatus('<i class="bi bi-exclamation-circle"></i> 请先选择软件需求。', 'danger');
      return;
    }
    var d = reqData[reqId];
    if (!d || !d.description || d.description.trim().length < 10) {
      setStatus('<i class="bi bi-exclamation-circle"></i> 该需求描述为空或过短（少于 10 个字符），'
        + '请先在【软件需求】中补充完整。', 'danger');
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>正在调用大模型…';
    setStatus('<span class="spinner-border spinner-border-sm me-1"></span>'
      + '正在调用大语言模型生成测试用例，请稍候（可能需要数十秒）…', 'muted');

    var form = new FormData();
    form.append('requirement_id', reqId);
    form.append('count', countEl.value);
    form.append('extra', extraEl.value || '');

    fetch(btn.dataset.url, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: form,
      credentials: 'same-origin'
    }).then(function (resp) {
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    }).then(function (res) {
      var data = res.data || {};
      if (!res.ok || !data.ok) {
        setStatus('<i class="bi bi-x-circle"></i> 生成失败：' + esc(data.error || '未知错误')
          + '<br><span class="text-muted">系统未生成任何用例，可以修正后重新提交。</span>', 'danger');
        return;
      }
      renderResults(data.results || []);
      setStatus('<i class="bi bi-check-circle"></i> 模型已返回 '
        + (data.results || []).length + ' 条用例，请逐条核对后保存。', 'success');
    }).catch(function (err) {
      setStatus('<i class="bi bi-x-circle"></i> 请求异常：' + esc(err.message)
        + '<br><span class="text-muted">请检查网络连接后重试；已保存的数据不受影响。</span>', 'danger');
    }).then(function () {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-magic"></i> 提交生成';
    });
  });

  if (toggleAll) {
    toggleAll.addEventListener('click', function () {
      var boxes = body.querySelectorAll('input[name$="-selected"]');
      var allOn = Array.prototype.every.call(boxes, function (b) { return b.checked; });
      boxes.forEach(function (b) { b.checked = !allOn; });
      updateCount();
    });
  }

  body.addEventListener('change', function (e) {
    if (e.target.name && e.target.name.indexOf('-selected') > -1) { updateCount(); }
  });

  window.genUpdateCount = updateCount;
  updateCount();
})();
