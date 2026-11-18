import fs from 'node:fs';import assert from 'node:assert/strict';import {chromium,webkit} from 'playwright';
const BASE=process.env.BASE||'http://127.0.0.1:4176';const src=fs.readFileSync('/home/ubuntu/studyBridge/audit_reports/learningmate_ec2_e2e_20260924T142154Z/tools/browser_race.js','utf8');const creds={email:src.match(/const EMAIL = '([^']+)'/)[1],password:src.match(/const PW = '([^']+)'/)[1]};const results=[];
for(const [engine,width] of [[chromium,1280],[chromium,393],[webkit,393],[webkit,430]]){
 const browser=await engine.launch();const ctx=await browser.newContext({viewport:{width,height:900}});const page=await ctx.newPage();page.on('dialog',d=>d.accept());let orig;
 const rec=(name,data={})=>{results.push({engine:engine.name(),width,name,...data});console.log(engine.name(),width,name,JSON.stringify(data));};
 try{
 await page.goto(BASE+'/login');await page.locator('[name=email]').fill(creds.email);await page.locator('[name=password]').fill(creds.password);await page.locator('[type=submit]').click();await page.waitForURL(u=>!u.pathname.endsWith('/login'));await page.goto(BASE+'/mypage');
 orig=await page.evaluate(async()=> (await fetch('/api/users/profile',{headers:{Authorization:'Bearer '+localStorage.token}})).json());
 for(const kind of ['name','major','both']){
  await page.getByRole('button',{name:'프로필 수정',exact:true}).click();const inputs=page.locator('input.input-field');const name=kind==='major'?orig.displayName:'QA수정',major=kind==='name'?orig.major:'QA전공';await inputs.nth(0).fill(name);await inputs.nth(1).fill(major||'');
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/users/profile')&&r.request().method()==='PUT');await page.getByRole('button',{name:'저장',exact:true}).click();const response=await pending;assert.equal(response.status(),200);const payload=response.request().postDataJSON();assert.deepEqual(Object.keys(payload).sort(),['displayName','major']);await page.getByRole('button',{name:'프로필 수정',exact:true}).waitFor();
  assert.equal(await inputs.nth(0).inputValue(),name);assert.equal(await inputs.nth(1).inputValue(),major||'전공 미설정');rec('profile '+kind+' HTTP/UI PASS',{status:response.status(),authorization:response.request().headers().authorization?'PRESENT':'MISSING',fields:Object.keys(payload)});
 }
 await page.getByRole('tab',{name:'내 신고',exact:true}).click();await page.getByTestId('my-report').first().waitFor();assert.ok((await page.getByTestId('my-report').first().innerText()).includes('삭제된'));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth),0);rec('my reports/deleted fallback/no overflow PASS');
 }catch(e){rec('FAIL',{error:e.message.slice(0,350)});}finally{if(orig)await page.evaluate(async orig=>{await fetch('/api/users/profile',{method:'PUT',headers:{Authorization:'Bearer '+localStorage.token,'Content-Type':'application/json'},body:JSON.stringify({displayName:orig.displayName,major:orig.major})});},orig);await browser.close();}
}
fs.writeFileSync('audit_reports/final-addon-2/profile.json',JSON.stringify(results,null,2));if(results.some(x=>x.name==='FAIL'))process.exitCode=1;
