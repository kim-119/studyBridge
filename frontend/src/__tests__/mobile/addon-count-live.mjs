import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chromium,webkit} from 'playwright';
const BASE=process.env.BASE||'http://127.0.0.1:4177';
const src=fs.readFileSync('/home/ubuntu/studyBridge/audit_reports/learningmate_ec2_e2e_20260924T142154Z/tools/browser_race.js','utf8');
const creds={email:src.match(/const EMAIL = '([^']+)'/)[1],password:src.match(/const PW = '([^']+)'/)[1]};
const results=[];
for(const [engine,width] of [[chromium,1280],[chromium,393],[webkit,393]]) {
 const browser=await engine.launch();const page=await browser.newPage({viewport:{width,height:900}});page.on('dialog',d=>d.accept());
 try {
  await page.goto(BASE+'/login');await page.locator('[name=email]').fill(creds.email);await page.locator('[name=password]').fill(creds.password);await page.locator('[type=submit]').click();await page.waitForURL(u=>!u.pathname.endsWith('/login'));
  await page.goto(BASE+'/review-notes');await page.getByTestId('review-note-card').first().getByRole('button',{name:'유사문제 풀기',exact:true}).click();
  const count=page.locator('select').filter({has:page.locator('option[value="5"]')});await count.selectOption('3');
  const pending=page.waitForResponse(r=>r.url().includes('/variant-question')&&r.request().method()==='POST',{timeout:190000});
  await page.getByRole('button',{name:'유사문제 생성',exact:true}).click();const response=await pending;const body=await response.json();
  assert.equal(response.status(),200);assert.equal(body.success,true,JSON.stringify({message:body.message,returned:body.returnedCount}));assert.equal(body.usedFallback,false);assert.ok(!body.partialFallback);assert.equal(body.questions.length,3);
  await page.getByTestId('similar-question-item').nth(2).waitFor();const rendered=await page.getByTestId('similar-question-item').count();assert.equal(rendered,3);
  for(let q=0;q<3;q++){await page.getByTestId('similar-question-item').nth(q).click();await page.getByTestId('similar-question-choice').first().click();await page.getByTestId('similar-question-submit').click();}
  const others=await page.getByTestId('similar-question-item').allTextContents();await page.getByTestId('similar-question-item').first().click();
  for(let attempt=2;attempt<=3;attempt++){await page.getByTestId('similar-question-retry').click();assert.equal(await page.getByTestId('similar-question-result').count(),0);assert.equal(await page.locator('[data-testid=similar-question-choice][aria-pressed=true]').count(),0);await page.getByTestId('similar-question-choice').nth(attempt-1).click();await page.getByTestId('similar-question-submit').click();}
  const after=await page.getByTestId('similar-question-item').allTextContents();assert.deepEqual(after.slice(1),others.slice(1));
  const r={engine:engine.name(),width,status:'PASS',noteId:body.reviewNoteId,selectedCount:3,requestCount:response.request().postDataJSON().count,backendReceivedCount:body.requestedCount,frontendRenderedCount:rendered,returnedCount:body.returnedCount};results.push(r);console.log(JSON.stringify(r));
 }catch(e){const r={engine:engine.name(),width,status:'FAIL',error:e.message.slice(0,500)};results.push(r);console.log(JSON.stringify(r));}finally{await browser.close();}
}
fs.writeFileSync('audit_reports/final-addon-2/count-live.json',JSON.stringify(results,null,2));if(results.some(r=>r.status==='FAIL'))process.exitCode=1;
