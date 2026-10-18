/* PIS-2 // WICKER BASIN -- terminal behaviour shared by every page. */
(function () {
  var html = document.documentElement;
  var ROOT = html.getAttribute('data-root') || '';
  var PAGE = html.getAttribute('data-id') || '';

  function sget(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function sset(k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} }
  function sdel(k) { try { sessionStorage.removeItem(k); } catch (e) {} }
  function $(id) { return document.getElementById(id); }
  function pad(n, w) { n = String(n); while (n.length < (w || 2)) n = '0' + n; return n; }
  function zulu() { var d = new Date(); return '14 OCT 1997 ' + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + 'Z'; }
  function acked() { return sget('ona_ack') === '1'; }
  function viewed() { try { return JSON.parse(sget('ona_viewed') || '[]'); } catch (e) { return []; } }
  function violations() { return Number(sget('ona_viol')) || 0; }
  function addViolation() { var n = violations() + 1; sset('ona_viol', String(n)); return n; }

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
    $('notice-text').innerHTML =
      '<pre>CONNECTION TERMINATED BY USER.\n\n' +
      'TERMINAL ........ T-0417\n' +
      'TIME ............ ' + zulu() + '\n' +
      'STATUS .......... CONTACT LOGGED\n\n' +
      'REPORT THIS CONTACT TO YOUR SECURITY OFFICER WITHIN 24 HOURS.</pre>' +
      '<hr><p class="small">[ <a href="' + ROOT + 'index.html">Reconnect</a> ]</p>';
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
    var t = 'RESOURCE ........... /custodian/' + (res === 'CUSTODIAN' ? '' : res + '/') + '\n' +
            'REQUIRED ........... CUSTODIAN\n' +
            'HELD ............... WICKER-3\n' +
            'OPERATOR ........... 7741-K\n' +
            'TERMINAL ........... T-0417\n' +
            'TIME ............... ' + zulu() + '\n' +
            'REFERENCE .......... SEC-971014-0417-' + pad(Math.floor(Math.random() * 9000) + 1000, 4) + '\n\n' +
            'THIS REQUEST HAS BEEN RECORDED AND FORWARDED TO THE PROGRAM SECURITY OFFICER. DO NOT REPEAT IT.';
    if (n === 2) t += '\n\nSECOND ATTEMPT RECORDED IN THIS SESSION. TERMINAL T-0417 HAS BEEN FLAGGED FOR REVIEW.';
    if (n >= 3) t += '\n\nATTEMPT ' + n + ' RECORDED IN THIS SESSION.\nTHIS SESSION IS NOW SUBJECT TO REAL-TIME MONITORING.\nREMAIN AT YOUR TERMINAL.';
    dn.textContent = t;
  }

  /* ---------------- log off ---------------- */
  var lo = $('lo-body');
  if (lo) {
    if (!acked()) {
      lo.textContent = 'NO ACTIVE SESSION ON TERMINAL T-0417.';
    } else {
      var s = Math.max(0, Math.floor((Date.now() - (Number(sget('ona_t0')) || Date.now())) / 1000));
      lo.textContent =
        'SESSION CLOSED.\n\n' +
        'OPERATOR ........... 7741-K\n' +
        'TERMINAL ........... T-0417\n' +
        'TIME ............... ' + zulu() + '\n' +
        'DURATION ........... ' + pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60) + '\n' +
        'DOCUMENTS VIEWED ... ' + viewed().length + '\n' +
        'ACCESS VIOLATIONS .. ' + violations() + '\n\n' +
        'THIS SESSION RECORD HAS BEEN TRANSMITTED TO THE PROGRAM SECURITY OFFICER.\n' +
        'SECURE YOUR TERMINAL BEFORE LEAVING THE ROOM.';
      sdel('ona_ack'); sdel('ona_t0'); sdel('ona_viewed'); sdel('ona_viol');
    }
  }

  /* ---------------- search ---------------- */
  var FOLK = /moth\s*-?man|sasquatch|big\s*foot|chupacabra|dover\s*demon|jersey\s*devil|\bchamp\b|death\s*worm|olgoi|yeti|cryptid/i;
  var RESTRICT = /custodian|annex\s*-?\s*k\b|\bline\s*-?\s*7\b|\bl-?7\b|site\s*-?\s*22|ba\s*-?\s*0?(33|40)\b/i;

  function hsh(str) { var h = 7; for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0; return h; }

  var sf = $('sf');
  if (sf) sf.onsubmit = function (e) {
    e.preventDefault();
    var q = $('sq').value.replace(/\s+/g, ' ').trim();
    var out = $('sr');
    out.style.display = 'block';
    while (out.firstChild) out.removeChild(out.firstChild);
    function line(str) { out.appendChild(document.createTextNode(str + '\n')); }

    if (!q) { line('NO QUERY ENTERED.'); return; }
    line('QUERY .............. "' + q + '"');
    line('TIME ............... ' + zulu());
    line('');

    if (FOLK.test(q)) {
      if (acked()) addViolation();
      line('NOTICE: QUERY CONTAINS A PUBLIC CORRELATION TERM.');
      line('USE OF FOLKLORE NAMES IS A REPORTABLE VIOLATION UNDER DIRECTIVE 91-02.');
      line('THIS QUERY HAS BEEN LOGGED. NO RESULTS RETURNED.');
      return;
    }
    if (RESTRICT.test(q)) {
      if (acked()) addViolation();
      line('QUERY TERM RESTRICTED.');
      line('THIS QUERY HAS BEEN FORWARDED TO CUSTODIAN.');
      return;
    }

    var index = window.PIS_INDEX || [];
    var words = q.toLowerCase().split(' ').filter(function (w) { return w.length >= 2; });
    var hits = index.filter(function (d) {
      var hay = (d.i + ' ' + d.t + ' ' + d.s + ' ' + d.k).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    });
    var withheld = 2 + (hsh(q.toLowerCase()) % 31);
    line('DOCUMENTS MATCHED .. ' + (hits.length + withheld));
    line('  AVAILABLE ........ ' + hits.length);
    line('  WITHHELD ......... ' + withheld + '  (ACCESS LEVEL INSUFFICIENT)');
    line('');
    if (/\bellen\b/i.test(q)) {
      line('NOTE: NO PERSON OF THIS NAME APPEARS IN ANY PROGRAM RECORD.');
      line('');
    }
    if (!hits.length) { line('NO DOCUMENTS AVAILABLE AT ACCESS LEVEL WICKER-3.'); return; }
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
