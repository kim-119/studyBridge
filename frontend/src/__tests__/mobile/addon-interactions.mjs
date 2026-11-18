import fs from 'node:fs'; import assert from 'node:assert/strict'; import {chromium,webkit} from 'playwright';
const BASE=process.env.BASE||'http://127.0.0.1:4175';
const src=fs.readFileSync('/home/ubuntu/studyBridge/audit_reports/learningmate_ec2_e2e_20260924T142154Z/tools/browser_race.js','utf8');
const creds={email:src.match(/const EMAIL = '([^']+)'/)[1],password:src.match(/const PW = '([^']+)'/)[1]};const results=[];
for(const [engine,width] of [[chromium,1280],[chromium,393],[webkit,393]]){
 const browser=await engine.launch();const context=await browser.newContext({viewport:{width,height:900}});const page=await context.newPage();page.on('dialog',d=>d.accept());
 let originalMemo; let noteId; const rec=(name,data={})=>{results.push({engine:engine.name(),width,name,...data});console.log(engine.name(),width,name,JSON.stringify(data));};
 try{
 await page.goto(BASE+'/login');await page.locator('[name=email]').fill(creds.email);await page.locator('[name=password]').fill(creds.password);await page.locator('[type=submit]').click();await page.waitForURL(u=>!u.pathname.endsWith('/login'));
 await page.goto(BASE+'/review-notes');const card=page.getByTestId('review-note-card').first();await card.waitFor();noteId=await card.getAttribute('data-note-id');
 await card.getByRole('button',{name:'메모',exact:true}).click();const memo=page.getByTestId('review-note-memo').first();originalMemo=await memo.inputValue();await memo.fill('');await memo.focus();const node=await memo.elementHandle();
 for(const text of ['abc','자료구조 개념 다시 공부하기','review binary tree','1-2-3 / O(n log n)','이 문제는 다시 복습해야 합니다.']){
  await page.keyboard.insertText(text);assert.ok(await memo.evaluate((e)=>document.activeElement===e&&!e.disabled));assert.ok(await node.evaluate(e=>e.isConnected));
 }
 // Exercise composition events on the actual focused DOM; physical Korean keyboard remains device acceptance.
 await memo.dispatchEvent('compositionstart',{data:''});await memo.dispatchEvent('compositionupdate',{data:'ㅎ'});await memo.dispatchEvent('compositionupdate',{data:'한'});await page.keyboard.insertText('한');await memo.dispatchEvent('compositionend',{data:'한'});
 const sentence=await memo.inputValue();await card.getByTestId('review-note-memo-save').click();await card.getByTestId('review-note-memo-status').waitFor();
 await page.reload();await page.getByTestId('review-note-card').first().getByRole('button',{name:'메모',exact:true}).click();assert.equal(await memo.inputValue(),sentence);rec('memo typing/composition/save/restore PASS');
 let requestCount;
 await page.route('**/variant-question',async route=>{requestCount=route.request().postDataJSON().count;await route.fulfill({json:{success:true,questions:Array.from({length:3},(_,i)=>({id:i+1,question:`문제 ${i+1}`,choices:['가','나','다','라'],correctAnswer:'가',explanation:'해설'}))}});});
 await page.getByTestId('review-note-card').first().getByRole('button',{name:'유사문제 풀기',exact:true}).click();await page.getByRole('button',{name:'유사문제 생성',exact:true}).click();await page.getByTestId('similar-question-item').nth(2).waitFor();assert.equal(await page.getByTestId('similar-question-item').count(),3);assert.equal(requestCount,3);
 for(let q=0;q<3;q++){await page.getByTestId('similar-question-item').nth(q).click();await page.getByTestId('similar-question-choice').nth(0).click();await page.getByTestId('similar-question-submit').click();}
 await page.getByTestId('similar-question-item').first().click();
 for(let attempt=2;attempt<=3;attempt++) {await page.getByTestId('similar-question-retry').click();assert.equal(await page.getByTestId('similar-question-result').count(),0);assert.equal(await page.getByTestId('similar-question-solver').getAttribute('data-attempt-status'),'READY');assert.equal(await page.locator('[data-testid=similar-question-choice][aria-pressed=true]').count(),0);await page.getByTestId('similar-question-choice').nth(attempt-1).click();await page.getByTestId('similar-question-submit').click();}
 assert.ok((await page.getByTestId('similar-question-item').nth(1).innerText()).includes('정답'));assert.ok((await page.getByTestId('similar-question-item').nth(2).innerText()).includes('정답'));
 rec('count/retry 3 attempts/independent PASS (AI response fixture)',{selectedCount:3,requestCount,frontendRenderedCount:3});
 await page.goto(BASE+'/review-notes');await page.getByTestId('review-note-card').first().getByRole('button',{name:'메모',exact:true}).click();assert.equal(await memo.inputValue(),sentence);rec('retry memo preserved PASS');
 await page.goto(BASE+'/archive/journal/366');await page.locator('.archive-split-view').waitFor();const m=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth-innerWidth,left:document.querySelector('.archive-left-panel').getBoundingClientRect().width,columns:getComputedStyle(document.querySelector('.archive-split-view')).gridTemplateColumns}));assert.equal(m.overflow,0);if(width<769)assert.ok(m.left>width*.7);rec('journal PASS',m);
 }catch(e){rec('FAIL',{error:e.message.slice(0,350)});}finally{
 if(noteId&&originalMemo!==undefined)await page.evaluate(async({noteId,memo})=>{await fetch(`/api/review-notes/${noteId}/memo`,{method:'PATCH',headers:{Authorization:'Bearer '+localStorage.token,'Content-Type':'application/json'},body:JSON.stringify({memo})});},{noteId,memo:originalMemo});
 await browser.close();}
}
fs.writeFileSync('audit_reports/final-addon-2/interactions.json',JSON.stringify(results,null,2));if(results.some(r=>r.name==='FAIL'))process.exitCode=1;
