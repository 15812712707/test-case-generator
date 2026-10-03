/* 通用前端交互
 * 1) 危险操作二次确认（对应说明书 3.7 / 6.3「删除等操作应提供确认机制」）
 * 2) 列表页批量勾选
 * 3) 表单防重复提交
 */
(function () {
  'use strict';

  // ---------- 1. 声明式确认弹窗 ----------
  // 用法：<form data-confirm="确定删除该用例吗？"> 或 <a data-confirm="..." href="...">
  function showConfirm(title, body, onOk) {
    var modalEl = document.getElementById('confirmModal');
    if (!modalEl || !window.bootstrap) {
      if (window.confirm(body)) { onOk(); }
      return;
    }
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmBody').innerHTML = body;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var okBtn = document.getElementById('confirmOk');
    var handler = function () {
      okBtn.removeEventListener('click', handler);
      modal.hide();
      onOk();
    };
    okBtn.addEventListener('click', handler);
    modal.show();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.dataset.confirm && !form.dataset.confirmed) {
      e.preventDefault();
      showConfirm(form.dataset.title || '操作确认', form.dataset.confirm, function () {
        form.dataset.confirmed = '1';
        if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
      });
      return;
    }
    // 防重复提交
    var btn = form.querySelector('button[type="submit"]');
    if (btn && !btn.dataset.keepEnabled) {
      setTimeout(function () {
        btn.disabled = true;
        btn.dataset.originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>处理中…';
      }, 0);
    }
  }, true);

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-confirm]');
    if (!el || el.tagName === 'FORM' || el.tagName === 'BUTTON') { return; }
    e.preventDefault();
    showConfirm(el.dataset.title || '操作确认', el.dataset.confirm, function () {
      window.location.href = el.getAttribute('href');
    });
  });

  // ---------- 2. 列表批量勾选 ----------
  document.addEventListener('change', function (e) {
    var all = e.target.closest('[data-check-all]');
    if (all) {
      var name = all.dataset.checkAll;
      document.querySelectorAll('input[name="' + name + '"]').forEach(function (cb) {
        cb.checked = all.checked;
      });
      updateBulkBar();
      return;
    }
    if (e.target.name === 'ids') { updateBulkBar(); }
  });

  function selectedIds() {
    return Array.prototype.slice
      .call(document.querySelectorAll('input[name="ids"]:checked'))
      .map(function (cb) { return cb.value; });
  }

  function updateBulkBar() {
    var bar = document.getElementById('bulkBar');
    if (!bar) { return; }
    var ids = selectedIds();
    bar.classList.toggle('d-none', ids.length === 0);
    var countEl = document.getElementById('bulkCount');
    if (countEl) { countEl.textContent = ids.length; }
    var exportLink = document.getElementById('bulkExport');
    if (exportLink) {
      var url = new URL(exportLink.dataset.base, window.location.origin);
      url.searchParams.set('ids', ids.join(','));
      exportLink.href = url.toString();
    }
    var form = document.getElementById('bulkDeleteForm');
    if (form) {
      form.dataset.confirm = '确定删除选中的 ' + ids.length + ' 条测试用例吗？删除后可在回收站还原。';
    }
  }

  // 把当前筛选条件带进批量操作表单
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('bulkDeleteForm');
    if (form) {
      new URLSearchParams(window.location.search).forEach(function (v, k) {
        if (k === 'page') { return; }
        var input = document.createElement('input');
        input.type = 'hidden'; input.name = k; input.value = v;
        form.appendChild(input);
      });
    }
    updateBulkBar();
  });

  window.appSelectedIds = selectedIds;
})();
