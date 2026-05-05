/* 节日特效引擎
 *
 * 由 base.html 在已登录页面注入 window.__HOLIDAY__ = {key, theme, name, title, subtitle, ...}。
 * 用户点 X 关闭后写 localStorage["holiday_dismissed_{key}"] = 1，整段假期不再弹。
 * 同会话内（页面跳转）用 sessionStorage 防重复弹出，但刷新窗口/新标签页可重新弹出（直到关闭）。
 */
(function () {
  'use strict';

  var holiday = window.__HOLIDAY__;
  if (!holiday || !holiday.key) return;

  var DISMISS_KEY = 'holiday_dismissed_' + holiday.key;
  var SESSION_KEY = 'holiday_session_seen_' + holiday.key;

  try {
    if (localStorage.getItem(DISMISS_KEY)) return;
    if (sessionStorage.getItem(SESSION_KEY)) return;
  } catch (e) {
    // localStorage 被禁用时直接放弃，避免每次刷新都触发
    return;
  }

  // 主题配置：emoji 池 + 卡片图标 + 粒子数 + 卡片彩带配色
  var THEMES = {
    new_year: {
      icon: '🎆',
      tag: 'NEW YEAR',
      emojis: ['🎆', '🎇', '🥂', '🎉', '✨', '⭐', '🌟'],
      particles: 70,
      drift: 100,
      sizeMin: 22, sizeMax: 36,
      durationMin: 7, durationMax: 11,
    },
    spring_festival: {
      icon: '🧧',
      tag: '新春',
      emojis: ['🧧', '🏮', '🎆', '🎇', '🐉', '✨', '🐍', '🐰'],
      particles: 90,
      drift: 80,
      sizeMin: 24, sizeMax: 40,
      durationMin: 7, durationMax: 12,
    },
    labor_day: {
      icon: '🔧',
      tag: '五一',
      emojis: ['🔧', '🛠️', '⚙️', '🚩', '⭐'],
      particles: 50,
      drift: 60,
      sizeMin: 20, sizeMax: 32,
      durationMin: 8, durationMax: 12,
    },
    dragon_boat: {
      icon: '🐲',
      tag: '端午',
      emojis: ['🥟', '🐲', '🍃', '🌿', '🚣'],
      particles: 60,
      drift: 70,
      sizeMin: 22, sizeMax: 36,
      durationMin: 8, durationMax: 12,
    },
    qixi: {
      icon: '💕',
      tag: '七夕',
      emojis: ['💖', '💕', '🌹', '✨', '💫', '🌸', '💗'],
      particles: 80,
      drift: 90,
      sizeMin: 18, sizeMax: 32,
      durationMin: 8, durationMax: 12,
    },
    mid_autumn: {
      icon: '🌕',
      tag: '中秋',
      emojis: ['🥮', '🌕', '🐰', '🌙', '✨', '🍂'],
      particles: 60,
      drift: 70,
      sizeMin: 22, sizeMax: 36,
      durationMin: 9, durationMax: 13,
    },
    national_day: {
      icon: '🇨🇳',
      tag: '国庆',
      emojis: ['🇨🇳', '🎆', '🎇', '⭐', '🌟', '✨'],
      particles: 80,
      drift: 100,
      sizeMin: 22, sizeMax: 38,
      durationMin: 7, durationMax: 11,
    },
    halloween: {
      icon: '🎃',
      tag: 'HALLOWEEN',
      emojis: ['🎃', '👻', '🦇', '🕷️', '🍬', '🕸️', '💀'],
      particles: 70,
      drift: 110,
      sizeMin: 22, sizeMax: 36,
      durationMin: 7, durationMax: 11,
    },
    christmas: {
      icon: '🎄',
      tag: 'CHRISTMAS',
      emojis: ['❄️', '🎄', '🎁', '⛄', '🌟', '🦌', '🎅'],
      particles: 100,
      drift: 80,
      sizeMin: 18, sizeMax: 32,
      durationMin: 9, durationMax: 14,
    },
  };

  var theme = THEMES[holiday.theme] || THEMES.spring_festival;

  function rand(min, max) { return Math.random() * (max - min) + min; }
  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  function buildOverlay() {
    var overlay = document.createElement('div');
    overlay.id = 'holiday-overlay';
    overlay.setAttribute('data-theme', holiday.theme);
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', holiday.name + ' 祝福');

    var bg = document.createElement('div');
    bg.className = 'holiday-bg';
    overlay.appendChild(bg);

    var card = document.createElement('div');
    card.className = 'holiday-card';

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'holiday-close';
    closeBtn.setAttribute('aria-label', '关闭节日特效');
    closeBtn.textContent = '×';
    card.appendChild(closeBtn);

    var icon = document.createElement('div');
    icon.className = 'holiday-card-icon';
    icon.textContent = theme.icon;
    card.appendChild(icon);

    if (theme.tag) {
      var tag = document.createElement('div');
      tag.className = 'holiday-card-tag';
      tag.textContent = theme.tag;
      card.appendChild(tag);
    }

    var title = document.createElement('h2');
    title.className = 'holiday-card-title';
    title.textContent = holiday.title || holiday.name;
    card.appendChild(title);

    if (holiday.subtitle) {
      var sub = document.createElement('p');
      sub.className = 'holiday-card-subtitle';
      sub.textContent = holiday.subtitle;
      card.appendChild(sub);
    }

    overlay.appendChild(card);
    return { overlay: overlay, closeBtn: closeBtn };
  }

  function spawnParticles(overlay) {
    var frag = document.createDocumentFragment();
    var w = window.innerWidth || 1024;
    var count = theme.particles || 60;
    // 平板/小屏减半，省性能
    if (w < 768) count = Math.round(count / 2);

    for (var i = 0; i < count; i++) {
      var p = document.createElement('span');
      p.className = 'holiday-particle';
      p.textContent = pick(theme.emojis);
      var size = rand(theme.sizeMin || 18, theme.sizeMax || 32);
      var duration = rand(theme.durationMin || 8, theme.durationMax || 12);
      var delay = rand(0, duration);
      var drift = rand(-theme.drift, theme.drift);
      var spin = rand(-540, 540);
      var opacity = rand(0.7, 1.0);

      p.style.left = rand(0, 100) + 'vw';
      p.style.setProperty('--p-size', size + 'px');
      p.style.setProperty('--p-duration', duration + 's');
      p.style.setProperty('--p-drift', drift + 'px');
      p.style.setProperty('--p-spin', spin + 'deg');
      p.style.setProperty('--p-opacity', opacity);
      p.style.animationDelay = '-' + delay + 's';

      frag.appendChild(p);
    }
    overlay.appendChild(frag);
  }

  function dismiss(overlay, persistent) {
    overlay.classList.remove('holiday-show');
    overlay.classList.add('holiday-fadeout');
    setTimeout(function () {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }, 600);
    try {
      if (persistent) localStorage.setItem(DISMISS_KEY, '1');
      sessionStorage.setItem(SESSION_KEY, '1');
    } catch (e) { /* ignore */ }
  }

  function start() {
    var built = buildOverlay();
    var overlay = built.overlay;
    document.body.appendChild(overlay);
    spawnParticles(overlay);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        overlay.classList.add('holiday-show');
      });
    });

    built.closeBtn.addEventListener('click', function () { dismiss(overlay, true); });

    // ESC 也算关闭（持久化）
    function onKey(e) {
      if (e.key === 'Escape') {
        dismiss(overlay, true);
        document.removeEventListener('keydown', onKey);
      }
    }
    document.addEventListener('keydown', onKey);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
