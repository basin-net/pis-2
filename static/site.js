/* PIS-2 // WICKER BASIN -- terminal behaviour shared by every page and both editions. */
(function () {
  var html = document.documentElement;
  var ROOT = html.getAttribute('data-root') || '';
  var PAGE = html.getAttribute('data-id') || '';
  var LANG = /^ja/i.test(html.getAttribute('lang') || '') ? 'ja' : 'en';

  function sget(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function sset(k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} }
  function sdel(k) { try { sessionStorage.removeItem(k); } catch (e) {} }
  function $(id) { return document.getElementById(id); }
  function pad(n, w) { n = String(n); while (n.length < (w || 2)) n = '0' + n; return n; }
  function zulu() { var d = new Date(); return T.date + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + 'Z'; }
  function acked() { return sget('ona_ack') === '1'; }
  function viewed() { try { return JSON.parse(sget('ona_viewed') || '[]'); } catch (e) { return []; } }
  function violations() { return Number(sget('ona_viol')) || 0; }
  function addViolation() { var n = violations() + 1; sset('ona_viol', String(n)); return n; }

  /* ---------------- strings ---------------- */
  var T = {
    en: {
      date: '14 OCT 1997 ',
      disc: function (t) {
        return 'CONNECTION TERMINATED BY USER.\n\n' +
          'TERMINAL ........ T-0417\n' +
          'TIME ............ ' + t + '\n' +
          'STATUS .......... CONTACT LOGGED\n\n' +
          'REPORT THIS CONTACT TO YOUR SECURITY OFFICER WITHIN 24 HOURS.';
      },
      reconnect: 'Reconnect',
      denied: function (res, t, ref) {
        return 'RESOURCE ........... /custodian/' + res + '\n' +
          'REQUIRED ........... CUSTODIAN\n' +
          'HELD ............... WICKER-3\n' +
          'OPERATOR ........... 7741-K\n' +
          'TERMINAL ........... T-0417\n' +
          'TIME ............... ' + t + '\n' +
          'REFERENCE .......... ' + ref + '\n\n' +
          'THIS REQUEST HAS BEEN RECORDED AND FORWARDED TO THE PROGRAM SECURITY OFFICER. DO NOT REPEAT IT.';
      },
      denied2: '\n\nSECOND ATTEMPT RECORDED IN THIS SESSION. TERMINAL T-0417 HAS BEEN FLAGGED FOR REVIEW.',
      denied3: function (n) {
        return '\n\nATTEMPT ' + n + ' RECORDED IN THIS SESSION.\nTHIS SESSION IS NOW SUBJECT TO REAL-TIME MONITORING.\nREMAIN AT YOUR TERMINAL.';
      },
      noSession: 'NO ACTIVE SESSION ON TERMINAL T-0417.',
      logoff: function (t, dur, nv, nx) {
        return 'SESSION CLOSED.\n\n' +
          'OPERATOR ........... 7741-K\n' +
          'TERMINAL ........... T-0417\n' +
          'TIME ............... ' + t + '\n' +
          'DURATION ........... ' + dur + '\n' +
          'DOCUMENTS VIEWED ... ' + nv + '\n' +
          'ACCESS VIOLATIONS .. ' + nx + '\n\n' +
          'THIS SESSION RECORD HAS BEEN TRANSMITTED TO THE PROGRAM SECURITY OFFICER.\n' +
          'SECURE YOUR TERMINAL BEFORE LEAVING THE ROOM.';
      },
      noQuery: 'NO QUERY ENTERED.',
      query: function (q) { return 'QUERY .............. "' + q + '"'; },
      time: 'TIME ............... ',
      restricted: ['QUERY TERM RESTRICTED.', 'THIS QUERY HAS BEEN FORWARDED TO CUSTODIAN.'],
      matched: 'DOCUMENTS MATCHED .. ',
      available: '  AVAILABLE ........ ',
      withheld: function (n) { return '  WITHHELD ......... ' + n + '  (ACCESS LEVEL INSUFFICIENT)'; },
      noPerson: 'NOTE: NO PERSON OF THIS NAME IS KNOWN TO THIS OFFICE.',
      noDocs: 'NO DOCUMENTS AVAILABLE AT ACCESS LEVEL WICKER-3.'
    },
    ja: {
      date: '1997年10月14日 ',
      disc: function (t) {
        return '利用者により接続が切断された。\n\n' +
          '端末 ............ T-0417\n' +
          '時刻 ............ ' + t + '\n' +
          '状態 ............ 接触を記録済み\n\n' +
          '24時間以内に担当保安官へこの接触を報告すること。';
      },
      reconnect: '再接続',
      denied: function (res, t, ref) {
        return '資源 ............... /custodian/' + res + '\n' +
          '必要権限 ........... CUSTODIAN\n' +
          '保有権限 ........... WICKER-3\n' +
          '操作員 ............. 7741-K\n' +
          '端末 ............... T-0417\n' +
          '時刻 ............... ' + t + '\n' +
          '照会番号 ........... ' + ref + '\n\n' +
          'この要求は記録され、計画保安官に転送された。同じ要求を繰り返してはならない。';
      },
      denied2: '\n\n本セッションで2回目の試行を記録した。端末 T-0417 は審査対象として登録された。',
      denied3: function (n) {
        return '\n\n本セッションで' + n + '回目の試行を記録した。\n本セッションは現在、リアルタイム監視下にある。\n端末の前を離れないこと。';
      },
      noSession: '端末 T-0417 に有効なセッションはない。',
      logoff: function (t, dur, nv, nx) {
        return 'セッションを終了した。\n\n' +
          '操作員 ............. 7741-K\n' +
          '端末 ............... T-0417\n' +
          '時刻 ............... ' + t + '\n' +
          '利用時間 ........... ' + dur + '\n' +
          '閲覧文書数 ......... ' + nv + '\n' +
          'アクセス違反 ....... ' + nx + '\n\n' +
          '本セッションの記録は計画保安官に送信された。\n' +
          '退室前に端末を施錠すること。';
      },
      noQuery: '検索語が入力されていない。',
      query: function (q) { return '検索語 ............. 「' + q + '」'; },
      time: '時刻 ............... ',
      restricted: ['この検索語は制限されている。', '本検索は CUSTODIAN に転送された。'],
      matched: '該当文書 ........... ',
      available: '  閲覧可 ........... ',
      withheld: function (n) { return '  非開示 ........... ' + n + '（権限不足）'; },
      noPerson: '注記：この名の人物は当局では把握されていない。',
      noDocs: '権限 WICKER-3 で閲覧できる文書はない。'
    }
  }[LANG];

  /* ---------------- clock ---------------- */
  var clocks = document.querySelectorAll('.systime');
  for (var i = 0; i < clocks.length; i++) clocks[i].textContent = zulu();

  /* ---------------- entry notice ---------------- */
  var ack = $('b-ack'), disc = $('b-disc');
  if (ack) ack.onclick = function () {
    sset('ona_ack', '1');
    sset('ona_t0', String(Date.now()));
    sset('ona_viewed', '[]');
    sset('ona_viol', '0');
    html.className = '';
    track();
    window.scrollTo(0, 0);
  };
  if (disc) disc.onclick = function () {
    var pre = document.createElement('pre');
    pre.textContent = T.disc(zulu());
    $('notice-text').innerHTML =
      pre.outerHTML +
      '<hr><p class="small">[ <a href="' + ROOT + 'index.html">' + T.reconnect + '</a> ]</p>';
  };

  function track() {
    if (!acked() || html.getAttribute('data-track') !== 'yes') return;
    var v = viewed();
    if (v.indexOf(PAGE) === -1) { v.push(PAGE); sset('ona_viewed', JSON.stringify(v)); }
  }
  track();

  /* ---------------- access denied ---------------- */
  var dn = $('dn-body');
  if (dn) {
    var m = /[?&]r=([^&]*)/.exec(location.search);
    var res = 'UNKNOWN';
    try { res = m ? decodeURIComponent(m[1]) : 'UNKNOWN'; } catch (e) {}
    res = res.toUpperCase().replace(/[^A-Z0-9\-]/g, '').slice(0, 24) || 'UNKNOWN';
    var n = acked() ? addViolation() : 1;
    var t = T.denied(res === 'CUSTODIAN' ? '' : res + '/', zulu(),
                     'SEC-971014-0417-' + pad(Math.floor(Math.random() * 9000) + 1000, 4));
    if (n === 2) t += T.denied2;
    if (n >= 3) t += T.denied3(n);
    dn.textContent = t;
  }

  /* ---------------- log off ---------------- */
  var lo = $('lo-body');
  if (lo) {
    if (!acked()) {
      lo.textContent = T.noSession;
    } else {
      var s = Math.max(0, Math.floor((Date.now() - (Number(sget('ona_t0')) || Date.now())) / 1000));
      lo.textContent = T.logoff(zulu(),
        pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60),
        viewed().length, violations());
      sdel('ona_ack'); sdel('ona_t0'); sdel('ona_viewed'); sdel('ona_viol');
    }
  }

  /* ---------------- search ---------------- */
  var RESTRICT = /custodian|カストディアン|annex\s*-?\s*k\b|附属書\s*k|\bline\s*-?\s*7\b|\bl-?7\b|ライン\s*7/i;

  function hsh(str) { var h = 7; for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0; return h; }

  var sf = $('sf');
  if (sf) sf.onsubmit = function (e) {
    e.preventDefault();
    var q = $('sq').value.replace(/\s+/g, ' ').trim();
    var out = $('sr');
    out.style.display = 'block';
    while (out.firstChild) out.removeChild(out.firstChild);
    function line(str) { out.appendChild(document.createTextNode(str + '\n')); }

    if (!q) { line(T.noQuery); return; }
    line(T.query(q));
    line(T.time + zulu());
    line('');

    if (RESTRICT.test(q)) {
      if (acked()) addViolation();
      line(T.restricted[0]);
      line(T.restricted[1]);
      return;
    }

    var index = window.PIS_INDEX || [];
    /* A single Japanese character is a meaningful word; a single Latin letter is not. */
    var words = q.toLowerCase().split(' ').filter(function (w) { return w.length >= 2 || /[^\x00-\x7f]/.test(w); });
    var hits = index.filter(function (d) {
      var hay = (d.i + ' ' + d.t + ' ' + d.s + ' ' + d.k).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    });
    var withheld = 2 + (hsh(q.toLowerCase()) % 31);
    line(T.matched + (hits.length + withheld));
    line(T.available + hits.length);
    line(T.withheld(withheld));
    line('');
    if (/\bellen\b|エレン/i.test(q)) {
      line(T.noPerson);
      line('');
    }
    if (!hits.length) { line(T.noDocs); return; }
    hits.slice(0, 40).forEach(function (d, i) {
      out.appendChild(document.createTextNode(pad(i + 1) + '. '));
      var a = document.createElement('a');
      a.href = ROOT + d.u;
      a.textContent = d.i + ' -- ' + d.t;
      out.appendChild(a);
      out.appendChild(document.createTextNode('\n'));
    });
  };

  /* ---------------- audio ---------------- */
  var current = null;
  function fmt(t) { t = Math.max(0, Math.floor(t || 0)); return pad(Math.floor(t / 60)) + ':' + pad(t % 60); }
  var players = document.querySelectorAll('.aud');
  Array.prototype.forEach.call(players, function (p) {
    var audio = null;
    var label = p.querySelector('.at');
    var total = label.textContent.split('/')[1] || '';
    function stop() {
      if (!audio) return;
      audio.pause();
      audio.currentTime = 0;
      label.textContent = '00:00 /' + total;
      if (current === stop) current = null;
    }
    p.querySelector('.ap').onclick = function () {
      if (current && current !== stop) current();
      if (!audio) {
        audio = new Audio(p.getAttribute('data-src'));
        audio.addEventListener('timeupdate', function () { label.textContent = fmt(audio.currentTime) + ' /' + total; });
        audio.addEventListener('ended', stop);
      }
      current = stop;
      audio.play();
    };
    p.querySelector('.as').onclick = stop;
  });
})();
