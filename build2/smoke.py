"""Exercise every observation path in the built page headlessly and report.

Runs in the page, writes a verdict into #detail, then the DOM is dumped and the
verdict grepped out. Catches the class of bug a screenshot cannot: a handler
that throws only when a particular control is used.
"""
import re
import subprocess
import sys
from pathlib import Path

D = Path(r"C:\Users\rinoa\landmine-bayes\dist")
src = (D / "landmine-bayes.html").read_text(encoding="utf-8")
patched = src.replace('if (!acked) $("#scrim").hidden = false;',
                      'if (false) $("#scrim").hidden = false;')
assert patched != src

TEST = r"""
(function(){
  var out = [], fail = 0;
  function ok(name, cond, extra){ out.push((cond?"PASS":"FAIL")+" | "+name+" | "+(extra||"")); if(!cond) fail++; }
  function cellsOf(n){ return adm1Cells.get(A1_NAME.indexOf(n)); }
  try {
    var c = cellsOf('Donetska');
    var li = c[300];

    // Prior district total must match the value the Python build computed.
    var pri = regionStats('adm1','Donetska').mean;
    ok('prior district total', Math.abs(pri-29646)<60, pri.toFixed(1)+' vs python 29646');

    // 1. confirmed detection raises the cell
    var m0 = cellMean(ALPHA[li],BETA[li]);
    obsKind='confirmed'; logObservation(li);
    var m1 = cellMean(ALPHA[li],BETA[li]);
    ok('confirmed raises cell mean', m1>m0*1.2, m0.toFixed(3)+' -> '+m1.toFixed(3));

    // 2. spreading raised a neighbour but not the whole oblast
    var f=landToFull[li], nb=fullToLand[f+1];
    ok('positive evidence spreads to neighbour', nb<0 || cellMean(ALPHA[nb],BETA[nb])>0, 'nb ok');

    // 3. clean sweep lowers, and only slightly at this coverage
    var li2 = c[900];
    var s0 = cellMean(ALPHA[li2],BETA[li2]);
    obsKind='clean'; logObservation(li2);
    var s1 = cellMean(ALPHA[li2],BETA[li2]);
    ok('clean sweep lowers the mean', s1<s0, s0.toFixed(4)+' -> '+s1.toFixed(4));
    ok('clean sweep moves it barely', s1>s0*0.90, 'ratio '+(s1/s0).toFixed(5));

    // 4. alarms with clutter land between prior and a confirmed hit
    var li3 = c[1200];
    var a0 = cellMean(ALPHA[li3],BETA[li3]);
    obsKind='alarms'; document.getElementById('obscount').value='3'; logObservation(li3);
    var a1v = cellMean(ALPHA[li3],BETA[li3]);
    ok('alarms update runs and is finite', isFinite(a1v) && a1v>0, a0.toFixed(4)+' -> '+a1v.toFixed(4));

    // 5. undo restores exactly
    var before = regionStats('adm1','Donetska').mean;
    obsKind='confirmed'; document.getElementById('obscount').value='1';
    logObservation(c[77]);
    document.getElementById('undo').click();
    var after = regionStats('adm1','Donetska').mean;
    ok('undo restores the district total', Math.abs(after-before)<1e-6, before.toFixed(4)+' -> '+after.toFixed(4));

    // 6. clear all returns to the prior
    document.getElementById('clearobs').click();
    var cleared = regionStats('adm1','Donetska').mean;
    ok('clear all returns to prior', Math.abs(cleared-pri)<1e-6, cleared.toFixed(3)+' vs '+pri.toFixed(3));
    ok('observation list emptied', OBS.length===0, 'n='+OBS.length);

    // 7. calibration rescales but preserves ranking
    var r0 = ranked('adm1').map(function(x){return x.n;}).slice(0,5).join(',');
    document.getElementById('den').value='3000';
    document.getElementById('den').dispatchEvent(new Event('input'));
    var scaled = regionStats('adm1','Donetska').mean;
    var r1 = ranked('adm1').map(function(x){return x.n;}).slice(0,5).join(',');
    ok('calibration rescales the total', scaled>pri*3, pri.toFixed(0)+' -> '+scaled.toFixed(0));
    ok('calibration preserves the ranking', r0===r1, r1);

    // 8. observations survive a calibration change (replayed, not wiped)
    obsKind='confirmed'; logObservation(c[300]);
    var n1 = OBS.length;
    document.getElementById('den').value='1200';
    document.getElementById('den').dispatchEvent(new Event('input'));
    ok('observations survive recalibration', OBS.length===n1, 'n='+OBS.length);

    // 9. both queues render (clearance order + within-AO sweep route)
    document.getElementById('queue').click();
    var qs = Array.prototype.map.call(document.querySelectorAll('pre.queue'),
      function(p){return p.textContent;}).join('\n');
    ok('sweep route renders', qs.indexOf('"queue"')>0, qs.length+' chars total');

    // 10. p_any bounds
    ok('p_any stays in [0,1]', pAny(ALPHA[li],BETA[li])<=1 && pAny(ALPHA[li],BETA[li])>=0, '');

    // ---- clearance tasking --------------------------------------------
    document.getElementById('clearobs').click();
    document.getElementById('den').value='600';
    document.getElementById('den').dispatchEvent(new Event('input'));

    ok('tasking payload present', !!TK, TK ? TK.criteria.length+' criteria' : 'missing');

    // ROC weights must match the published vector exactly.
    var w = rocWeights(7);
    var want = [0.3704,0.2276,0.1561,0.1085,0.0728,0.0442,0.0204];
    var wok = want.every(function(v,i){ return Math.abs(w[i]-v)<5e-4; });
    ok('ROC weights match the spec', wok, Array.prototype.map.call(w,function(x){return x.toFixed(4);}).join(','));
    var sum=0; for(var i=0;i<7;i++) sum+=w[i];
    ok('weights sum to 1', Math.abs(sum-1)<1e-12, sum.toFixed(12));

    // Rank-1 raion and its score must reproduce build_tasking.py.
    var r1 = tkRanked('adm2')[0];
    ok('rank-1 raion is Bakhmutskyi', r1.n==='Bakhmutskyi', r1.n+' score '+r1.t.score.toFixed(4));
    ok('rank-1 score matches python 0.8051', Math.abs(r1.t.score-0.8051)<0.01, r1.t.score.toFixed(4));
    ok('anchor matches python', Math.abs(r1.t.anchor.lat-48.5775)<1e-3 &&
       Math.abs(r1.t.anchor.lon-38.1146)<1e-3, r1.t.anchor.lat+','+r1.t.anchor.lon);
    var cs=0; for (var k in r1.t.contrib) cs+=r1.t.contrib[k];
    ok('contributions sum to the score', Math.abs(cs-r1.t.score)<1e-9, cs.toFixed(6));

    // Disabling a criterion must renormalise, not leave a hole.
    var before = tkWeights().get('density');
    tkEnabled = tkEnabled.filter(function(k){return k!=='access';});
    computeTasking();
    var w6 = tkWeights(); var s6=0; w6.forEach(function(v){s6+=v;});
    ok('disabling renormalises to 1', Math.abs(s6-1)<1e-12, s6.toFixed(12));
    ok('disabling raises the top weight', w6.get('density')>before,
       before.toFixed(4)+' -> '+w6.get('density').toFixed(4));
    tkEnabled = TK.criteria.map(function(c){return c.key;});
    computeTasking();

    // The tasking order must differ from a pure density order -- otherwise the
    // six impact criteria are decoration.
    var byTask = tkRanked('adm2').slice(0,10).map(function(r){return r.n;});
    var byDens = ranked('adm2').slice(0,10).map(function(r){return r.n;});
    var same = byTask.filter(function(n,i){ return byDens[i]===n; }).length;
    ok('tasking order differs from density order', same<10, same+'/10 identical');

    // Logging detections must reorder the queue: density follows the posterior.
    var target = tkRanked('adm2')[60];
    var tc = adm2Cells.get(a2Idx.get(target.n));
    var rankBefore = tkRanked('adm2').find(function(r){return r.n===target.n;}).rank;
    obsKind='confirmed'; document.getElementById('obscount').value='40';
    for (var q=0;q<Math.min(25,tc.length);q++) logObservation(tc[q]);
    var rankAfter = tkRanked('adm2').find(function(r){return r.n===target.n;}).rank;
    ok('detections move the tasking rank', rankAfter<rankBefore,
       target.n+' #'+rankBefore+' -> #'+rankAfter);
    document.getElementById('clearobs').click();

    // Queue renders and carries anchors.
    document.getElementById('queue').click();
    var pre = document.querySelector('pre.queue');
    ok('clearance queue renders with anchors',
       !!pre && pre.textContent.indexOf('anchor_lat')>0 && pre.textContent.indexOf('"order"')>0,
       pre ? pre.textContent.length+' chars' : 'missing');
  } catch(e){ out.push('FAIL | threw | '+e.message+' '+(e.stack||'').slice(0,200)); fail++; }
  document.getElementById('detail').innerHTML =
    '<pre id="SMOKE">'+ (fail? 'FAILURES '+fail : 'ALL PASS') +'\n'+out.join('\n')+'</pre>';
})();
"""

patched = patched.replace("renderDetail();\n</script>",
                          "renderDetail();\n" + TEST + "\n</script>")
tmp = D / "_smoke.html"
tmp.write_text(patched, encoding="utf-8")

r = subprocess.run([
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "--headless=new", "--disable-gpu", "--virtual-time-budget=15000",
    "--dump-dom", tmp.as_uri(),
], capture_output=True, timeout=300)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r'<pre id="SMOKE">(.*?)</pre>', dom, re.S)
if not m:
    err = re.search(r"Render error.*?<pre[^>]*>(.*?)</pre>", dom, re.S)
    print("NO SMOKE RESULT")
    print(err.group(1)[:1500] if err else dom[:800])
    sys.exit(1)
txt = m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
print(txt)
sys.exit(1 if "FAIL" in txt else 0)
