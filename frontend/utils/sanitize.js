(function (global) {
  'use strict';

  var ALLOWED_TAGS = {
    a: true, b: true, blockquote: true, br: true, code: true, div: true,
    em: true, hr: true, i: true, img: true, li: true, ol: true, p: true,
    pre: true, span: true, strong: true, table: true, tbody: true, td: true,
    th: true, thead: true, tr: true, u: true, ul: true
  };
  var VOID_TAGS = { br: true, hr: true, img: true };
  var GLOBAL_ATTRS = { class: true, id: true, title: true };
  var TAG_ATTRS = {
    a: { href: true, target: true, rel: true },
    img: { src: true, alt: true, width: true, height: true, class: true },
    td: { colspan: true, rowspan: true },
    th: { colspan: true, rowspan: true }
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function isSafeUrl(value, image) {
    if (!value) return false;
    value = String(value).trim();
    if (/[\x00-\x1f\x7f]/.test(value)) return false;
    if (value.charAt(0) === '#') return true;
    if (value.charAt(0) === '/' && value.slice(0, 2) !== '//') return true;
    if (value.slice(0, 2) !== '//' && !/^[a-z][a-z0-9+.-]*:/i.test(value)) return true;
    if (/^https?:\/\//i.test(value)) return true;
    if (!image && /^mailto:/i.test(value)) return true;
    if (image && /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$/i.test(value)) return true;
    return false;
  }

  function attrAllowed(tag, name) {
    return !!GLOBAL_ATTRS[name] || !!(TAG_ATTRS[tag] && TAG_ATTRS[tag][name]);
  }

  function sanitizeNode(node, doc) {
    if (node.nodeType === Node.TEXT_NODE) {
      return doc.createTextNode(node.nodeValue || '');
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return doc.createDocumentFragment();
    }

    var tag = node.tagName.toLowerCase();
    if (!ALLOWED_TAGS[tag]) {
      var fragment = doc.createDocumentFragment();
      Array.prototype.forEach.call(node.childNodes, function (child) {
        fragment.appendChild(sanitizeNode(child, doc));
      });
      return fragment;
    }

    var clean = doc.createElement(tag);
    Array.prototype.forEach.call(node.attributes, function (attr) {
      var name = attr.name.toLowerCase();
      var value = attr.value == null ? '' : String(attr.value);
      if (name.indexOf('on') === 0 || name === 'style' || !attrAllowed(tag, name)) return;
      if ((name === 'href' || name === 'src') && !isSafeUrl(value, tag === 'img')) return;
      if (name === 'target' && value !== '_blank' && value !== '_self') return;
      clean.setAttribute(name, value);
    });

    if (tag === 'a' && !clean.getAttribute('rel')) {
      clean.setAttribute('rel', 'noopener noreferrer');
    }
    if (!VOID_TAGS[tag]) {
      Array.prototype.forEach.call(node.childNodes, function (child) {
        clean.appendChild(sanitizeNode(child, doc));
      });
    }
    return clean;
  }

  function sanitizeRichHtml(input) {
    if (!input) return '';
    var template = document.createElement('template');
    template.innerHTML = String(input);
    var out = document.createElement('template');
    Array.prototype.forEach.call(template.content.childNodes, function (child) {
      out.content.appendChild(sanitizeNode(child, document));
    });
    return out.innerHTML;
  }

  function markdownImagesToHtml(input) {
    var text = String(input == null ? '' : input);
    var pattern = /!\[([^\]]*)\]\(([^)]+)\)/g;
    var html = '';
    var last = 0;
    var match;
    while ((match = pattern.exec(text)) !== null) {
      html += text.slice(last, match.index);
      var alt = match[1] || '图片';
      var url = String(match[2] || '').trim();
      if (isSafeUrl(url, true)) {
        html += '<img src="' + escapeHtml(url) + '" alt="' + escapeHtml(alt) + '" class="img-fluid">';
      } else {
        html += escapeHtml(match[0]);
      }
      last = pattern.lastIndex;
    }
    html += text.slice(last);
    return html;
  }

  global.sanitizeRichHtml = sanitizeRichHtml;
  global.safeQuestionHtml = function (input) {
    return sanitizeRichHtml(markdownImagesToHtml(input));
  };
  // 暴露 URL 协议白名单校验，供资源链接等场景使用
  global.isSafeUrl = isSafeUrl;
})(window);
