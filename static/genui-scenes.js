/* Lab Upgrade — scene layer for the site voice agent (genui-scenes.js).
 * Loaded by widget-genui.js. Renders catalog scenes full-screen over the site; no React, no external scripts. */
/* thinking-orbs 0.3.2 — MIT License, (c) 2026 Jakub Antalik */
(()=>{function Q(n,o,t){return n+(o-n)*t}function ct(n){return n-Math.floor(n)}function V(n,o){let t=Math.floor(n),a=Math.floor(o),c=n-t,s=o-a;c=c*c*(3-2*c),s=s*s*(3-2*s);let e=O(t,a),l=O(t+1,a),h=O(t,a+1),d=O(t+1,a+1);return e+(l-e)*c+(h-e)*s+(e-l-h+d)*c*s}function O(n,o){let t=Math.sin(n*12.9898+o*78.233)*43758.5453;return t-Math.floor(t)}function Z(n,o){let t=Math.PI*(3-Math.sqrt(5)),a=1-2*(n+.5)/o,c=Math.sqrt(1-a*a),s=n*t;return[c*Math.cos(s),a,c*Math.sin(s)]}function ut(n,o){return Math.atan2(Math.sin(n-o),Math.cos(n-o))}function F(n,o,t,a,c){let s=Math.sin(o),e=Math.cos(o),l=Math.sin(n),h=Math.cos(n);return(d,R,p)=>{let r=d*h+p*l,M=-d*l+p*h,x=R*e-M*s,b=R*s+M*e;return[t+r*c,a-x*c,b]}}function et(n,o,t,a){if(!a){let s=Math.round((t?1-n:n)*255);return`rgba(${s},${s},${s},${o})`}let c=s=>Math.round(t?s*(1-n):s+(255-s)*n);return`rgba(${c(a.r)},${c(a.g)},${c(a.b)},${o})`}function at(n,o,t,a=.3,c){for(let s of o){let e=s.a??1,l=Math.min(1,Math.max(0,s.white));n.fillStyle=et(l,e,t,c),n.beginPath(),n.arc(s.x,s.y,s.r,0,Math.PI*2),n.fill()}}function rt(n,o,t,a){for(let c of o){let s=c.a??1,e=Math.min(1,Math.max(0,c.white));n.strokeStyle=et(e,s,t,a),n.lineWidth=c.w,n.beginPath(),n.moveTo(c.x1,c.y1),n.lineTo(c.x2,c.y2),n.stroke()}}function B(n,o,t=.3){let a=[];for(let c of n)(c.a??1)<.02||(c.r=Math.max(t,c.r),a.push(c));return a.sort((c,s)=>c.z-s.z),{dots:a,lines:o.filter(c=>(c.a??1)>=.02)}}function j(n,o,t,a){o.lines.length&&rt(n,o.lines,t,a),at(n,o.dots,t,.3,a)}function T(n,o){return(n/300)**o}var dt=[["latRings","lonDensity"],["rings","lonDensity"],["lanes","segs"]],ft=["orbitN","ghostN","nodeN","strandN","signals"],mt=["iconD"],bt=["rBase","rDepth","rActive","rDot","ghostR","partR","partRDepth","nodeR","nodeRDepth"];function xt(n,o){let t={...n},a=new Set,c=Math.sqrt(o);for(let[s,e]of dt){let l=t[s],h=t[e];l!=null&&h!=null&&!a.has(s)&&!a.has(e)&&(t[s]=Math.max(2,Math.round(l*c)),t[e]=Math.max(2,Math.round(h*c)),a.add(s),a.add(e))}for(let s of ft){let e=t[s];e!=null&&e!==0&&!a.has(s)&&(t[s]=Math.max(1,Math.round(e*o)))}for(let s of mt){let e=t[s];e!=null&&(t[s]=Math.max(.02,e*o))}return t}function gt(n,o){let t={...n};for(let a of bt){let c=t[a];c!=null&&(t[a]=c*o)}return t.rSizeMul=(t.rSizeMul??1)*o,t}var yt={globe:{latRings:17,lonDensity:44,rBase:.6,rDepth:1.7,rBoost:1,inkFar:.62,inkSpan:.54,rsPow:.6,rMin:.3},orbits:{orbitN:12,ghostN:40,ghostR:.9,ghostA:.5,particles:3,partR:1.2,partRDepth:1.6,rsPow:.6,rMin:.3},rubik:{latRings:15,lonDensity:40,moveCount:14,rBase:.6,rDepth:1.7,rActive:.3,inkFar:.62,inkSpan:.54,rsPow:.6,rMin:.3},wave:{rings:15,lonDensity:40,rBase:.6,rDepth:1.7,rsPow:.6,rMin:.3},web:{nodeN:30,thr:.72,signals:5,nodeR:1.4,nodeRDepth:1.8,lineW:.8,rsPow:.6,rMin:.3},braid:{strandN:52,turns:3,ghostN:150,rBase:1.2,rDepth:1.8,rsPow:.6,rMin:.3},ribbon:{lanes:5,segs:88,ghostN:150,rBase:1.1,rDepth:1.7,rsPow:.6,rMin:.3},ring:{lanes:5,segs:88,ghostN:0,faceOn:1,rBase:1.1,rDepth:1.7,rsPow:.6,rMin:.3},morph:{rDot:.021,iconD:1,rMin:.25}},wt=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.76,e=F(o*.4,.3,a,c,1),l=T(n,t.rsPow??.6),h=[],d=t.ghostN??150;for(let r=0;r<d;r++){let M=Z(r,d),[x,b,i]=e(M[0]*s,M[1]*s,M[2]*s),u=(i/s+1)/2;h.push({x,y:b,z:i,r:.8*l,white:.78,a:.1+.22*u})}let R=t.strandN??52,p=t.turns??3;for(let r=0;r<3;r++){let M=r/3*2*Math.PI;for(let x=0;x<R;x++){let b=(ct(x/R+o*.045)*2-1)*.96,i=Math.sqrt(Math.max(0,1-b*b)),u=Math.min(1,(1-Math.abs(b))/.1),g=b*Math.PI*p+M,f=1+.075*Math.sin(b*Math.PI*p*2+M*2+o*.8),P=i*s*f,[y,D,m]=e(Math.cos(g)*P,b*s*f,Math.sin(g)*P),w=(m/s+1)/2;h.push({x:y,y:D,z:m,r:((t.rBase??1.2)+(t.rDepth??1.8)*w)*l,white:.55-.45*w,a:u*(.45+.55*w)})}}return B(h,[],t.rMin)};function Pt(n,o,t,a){let c=2*o*t+a,s=n%c,e=new Array(o).fill(0),l=-1;if(s<2*o*t){let h=Math.floor(s/t),d=(s-h*t)/t,p=1-(1-Math.min(1,d/.7))**3;if(h<o){for(let r=0;r<h;r++)e[r]=1;e[h]=p,l=h}else{let r=2*o-1-h;for(let M=0;M<r;M++)e[M]=1;e[r]=1-p,l=r}}return{amount:e,active:l}}function Rt(n,o,t){let[a,c,s]=n,e=!1;for(let l=0;l<o.length;l++){if(t.amount[l]<=0)continue;let h=o[l],d=h.axis===0?a:h.axis===1?c:s;if(d<h.lo||d>=h.hi)continue;l===t.active&&(e=!0);let R=h.ang*t.amount[l],p=Math.cos(R),r=Math.sin(R);if(h.axis===0){let M=c*p-s*r;s=c*r+s*p,c=M}else if(h.axis===1){let M=a*p+s*r;s=-a*r+s*p,a=M}else{let M=a*p-c*r;c=a*r+c*p,a=M}}return[a,c,s,e]}function Dt(n){let o=[];for(let t=0;t<n;t++){let a=Math.min(2,Math.floor(O(t,2.3)*3)),c=-1+.5*Math.min(3,Math.floor(O(t,5.9)*4)),s=O(t,7.7)<.5?1:-1;o.push({axis:a,lo:c,hi:c+.5,ang:s*Math.PI/2})}return o}var vt=(n,o,t)=>{let c=n/2,s=n/2,e=n/2*.82,l=.4+.06*Math.sin(o*.35),h=F(o*.5,l,c,s,e),d=o*(.5+(1.7-.5)*(t.scanMul??1)),R=T(n,t.rsPow??.6),p=t.dimBase??1,r=[],M=t.latRings??17,x=t.lonDensity??44;for(let b=0;b<=M;b++){let i=-Math.PI/2+b/M*Math.PI,u=Math.cos(i),g=Math.sin(i),f=Math.max(1,Math.round(Math.abs(u)*x));for(let P=0;P<f;P++){let y=P/f*2*Math.PI,[D,m,w]=h(u*Math.cos(y),g,u*Math.sin(y)),v=(w+1)/2,z=ut(y+o*.5,d),k=Math.exp(-(z*z)/.18)*Math.max(0,w);r.push({x:D,y:m,z:w,r:((t.rBase??.6)+(t.rDepth??1.7)*v+(t.rBoost??1)*k)*R,white:(t.inkFar??.62)-(t.inkSpan??.54)*v,a:p+(1-p)*Math.min(1,k)})}}return B(r,[],t.rMin)},zt=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.82,e=F(o*.55,.35+.1*Math.sin(o*.9),a,c,s),l=T(n,t.rsPow??.6),h=t.moveCount??14,d=Dt(h),R=Pt(o,h,.42,1.2),p=[],r=t.latRings??15,M=t.lonDensity??40;for(let x=0;x<=r;x++){let b=-Math.PI/2+x/r*Math.PI,i=Math.cos(b),u=Math.sin(b),g=Math.max(1,Math.round(Math.abs(i)*M));for(let f=0;f<g;f++){let P=f/g*2*Math.PI,[y,D,m,w]=Rt([i*Math.cos(P),u,i*Math.sin(P)],d,R),[v,z,k]=e(y,D,m),S=(k+1)/2;p.push({x:v,y:z,z:k,r:((t.rBase??.6)+(t.rDepth??1.7)*S+(w?t.rActive??.3:0))*l,white:(t.inkFar??.62)-(t.inkSpan??.54)*S-(w?.14:0)})}}return B(p,[],t.rMin)},St=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.874,e=F(o*.18,.38,a,c,1),l=T(n,t.rsPow??.6),h=[],d=t.rings??15,R=t.lonDensity??40;for(let p=0;p<=d;p++){let r=-Math.PI/2+p/d*Math.PI,M=Math.cos(r),x=Math.sin(r),b=.62*Math.sin(o*2.1-p*.52)+.38*Math.sin(o*1.27+p*.83),i=s*(.88+.105*b),u=Math.max(1,Math.round(Math.abs(M)*R));for(let g=0;g<u;g++){let f=g/u*2*Math.PI,[P,y,D]=e(M*Math.cos(f)*i,x*i,M*Math.sin(f)*i),m=(D/s+1)/2,w=Math.max(0,b);h.push({x:P,y,z:D,r:((t.rBase??.6)+(t.rDepth??1.7)*m)*(1+.4*w)*l,white:.66-.56*m-.1*w})}}return B(h,[],t.rMin)};function kt(n){return n*n*(3-2*n)}function it(n){let o=n.length,t=[],a=0;for(let c=0;c<o;c++){let s=n[c],e=n[(c+1)%o],l=Math.hypot(e[0]-s[0],e[1]-s[1]);t.push(l),a+=l}return c=>{let s=c*a,e=0;for(;s>t[e]&&e<o-1;)s-=t[e],e++;let l=n[e],h=n[(e+1)%o],d=t[e]?Math.min(1,s/t[e]):0;return[l[0]+(h[0]-l[0])*d,l[1]+(h[1]-l[1])*d]}}var It=n=>{let o=-Math.PI/2+n*2*Math.PI;return[Math.cos(o)*.24,Math.sin(o)*.24]},Nt=it([[0,-.26],[.24,.16],[-.24,.16]]),Et=it([[0,-.2],[.2,-.2],[.2,.2],[-.2,.2],[-.2,-.2]]),J=[It,Nt,Et];function Ot(n){return Math.max(6,Math.round(34*n))}var X=1.4,ht=.9,$=X+ht,At=(n,o,t)=>{let a=J.length,c=o%($*a),s=t.shape!=null&&t.shape>=0&&t.shape<a?Math.floor(t.shape):-1,e=s>=0?s:Math.floor(c/$),l=s>=0?o%$:c-e*$,h=s>=0?0:l>X?kt((l-X)/ht):0,d=t.spread??1,R=J[e],p=s>=0?R:J[(e+1)%a],r=160,M=[];for(let m=0;m<r;m++){let w=m/r,v=R(w),z=p(w);M.push([(v[0]+(z[0]-v[0])*h)*d,(v[1]+(z[1]-v[1])*h)*d])}let x=[],b=0;for(let m=0;m<r;m++){let w=M[m],v=M[(m+1)%r],z=Math.hypot(v[0]-w[0],v[1]-w[1]);x.push(z),b+=z}let i=Ot(t.iconD??1),u=(t.rDot??.021)*1.35*d,g=1+.02*Math.sin(l*3.1),f=[],P=n/2,y=0,D=0;for(let m=0;m<i;m++){let w=m/i*b;for(;D+x[y]<w&&y<r-1;)D+=x[y],y++;let v=M[y],z=M[(y+1)%r],k=x[y]?Math.min(1,(w-D)/x[y]):0,S=(v[0]+(z[0]-v[0])*k)*g,A=(v[1]+(z[1]-v[1])*k)*g;f.push({x:P+S*n,y:P+A*n,z:0,r:Math.max(.35,u*n),white:.1})}return B(f,[],t.rMin)},Bt=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.82,e=F(o*.12,.3,a,c,1),l=T(n,t.rsPow??.6),h=[],d=t.orbitN??12,R=t.ghostN??40,p=t.particles??3;for(let r=0;r<d;r++){let M=O(r,1.7),x=O(r,5.2),b=O(r,8.9),i=s*(.45+.52*M),u=M*2*Math.PI,g=Math.acos(2*x-1),f=Math.sin(g)*Math.cos(u),P=Math.cos(g),y=Math.sin(g)*Math.sin(u),D=-P,m=f,w=0,v=Math.max(1e-6,Math.sqrt(D*D+m*m));D/=v,m/=v;let z=P*w-y*m,k=y*D-f*w,S=f*m-P*D,A=(.25+.55*b)*(b>.5?1:-1);for(let E=0;E<R;E++){let I=E/R*2*Math.PI,[N,C,_]=e((D*Math.cos(I)+z*Math.sin(I))*i,(m*Math.cos(I)+k*Math.sin(I))*i,(w*Math.cos(I)+S*Math.sin(I))*i),L=(_/i+1)/2;h.push({x:N,y:C,z:_,r:(t.ghostR??.9)*l,white:.72,a:(t.ghostA??.5)*(.4+.6*L)})}for(let E=0;E<p;E++){let I=o*A+E/p*2*Math.PI+x*6,[N,C,_]=e((D*Math.cos(I)+z*Math.sin(I))*i,(m*Math.cos(I)+k*Math.sin(I))*i,(w*Math.cos(I)+S*Math.sin(I))*i),L=(_/i+1)/2;h.push({x:N,y:C,z:_,r:((t.partR??1.2)+(t.partRDepth??1.6)*L)*l,white:.3-.22*L})}}return B(h,[],t.rMin)},st=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.78,e=t.spin??1,l=.3,h=F(o*.1*e,l,a,c,1),d=T(n,t.rsPow??.6),R=[],p=t.ghostN??150;for(let S=0;S<p;S++){let A=Z(S,p),[E,I,N]=h(A[0]*s,A[1]*s,A[2]*s),C=(N/s+1)/2;R.push({x:E,y:I,z:N,r:.8*d,white:.78,a:.1+.22*C})}let r=o*.24*e,M=t.faceOn?-l:.55+.3*Math.sin(o*.18)*e,x=Math.cos(r),b=0,i=Math.sin(r),u=-i*Math.sin(M),g=Math.cos(M),f=x*Math.sin(M),P=b*f-i*g,y=i*u-x*f,D=x*g-b*u,m=.23*(t.wobMul??1),w=t.faceOn?s/(1+.85*m):s,v=t.lanes??5,z=t.segs??88,k=Math.max(1,Math.round(v*(t.bandMul??1)));for(let S=0;S<k;S++){let A=(S-(k-1)/2)*.075,E=Math.abs(S-(k-1)/2)/Math.max(1,(k-1)/2);for(let I=0;I<z;I++){let N=I/z*2*Math.PI,C=(.16*Math.sin(N*3-o*1.7+S*.22)+.07*Math.sin(N*5+o*1.1))*(t.wobMul??1),_=t.faceOn?1+C:1,L=t.faceOn?A:A+C,W=x*Math.cos(N)+u*Math.sin(N)+P*L,Y=b*Math.cos(N)+g*Math.sin(N)+y*L,K=i*Math.cos(N)+f*Math.sin(N)+D*L,U=Math.sqrt(W*W+Y*Y+K*K),G=w*_,[Mt,pt,nt]=h(W/U*G,Y/U*G,K/U*G),H=(nt/s+1)/2;R.push({x:Mt,y:pt,z:nt,r:((t.rBase??1.1)+(t.rDepth??1.7)*H)*(1-.25*E)*d,white:.52-.44*H+.18*E,a:.4+.6*H})}}return B(R,[],t.rMin)},Ct=(n,o,t)=>{let a=n/2,c=n/2,s=n/2*.8*(t.spread??1),e=F(o*.12,.32,a,c,s),l=T(n,t.rsPow??.6),h=t.nodeN??30,d=t.thr??.72,R=t.nodeR??1.4,p=t.nodeRDepth??1.8,r=[];for(let i=0;i<h;i++){let u=Z(i,h),g=u[0]+.3*(V(i*.31+9,o*.24)-.5)*2,f=u[1]+.3*(V(i*.53+27,o*.21)-.5)*2,P=u[2]+.3*(V(i*.77+55,o*.27)-.5)*2,y=Math.sqrt(g*g+f*f+P*P);r.push([g/y,f/y,P/y])}let M=[],x=[];for(let i=0;i<h;i++)for(let u=i+1;u<h;u++){let g=r[i][0]-r[u][0],f=r[i][1]-r[u][1],P=r[i][2]-r[u][2],y=Math.sqrt(g*g+f*f+P*P);if(y>=d)continue;let[D,m,w]=e(r[i][0],r[i][1],r[i][2]),[v,z,k]=e(r[u][0],r[u][1],r[u][2]),S=((w+k)/2+1)/2;M.push({x1:D,y1:m,x2:v,y2:z,white:.42,a:(1-y/d)*(.3+.55*S),w:Math.max(.6,(t.lineW??.8)*l)})}for(let i=0;i<h;i++){let[u,g,f]=e(r[i][0],r[i][1],r[i][2]),P=(f+1)/2,y=1+.25*Math.sin(o*1.4+i*2.7);x.push({x:u,y:g,z:f,r:(R+p*P)*y*l,white:.55-.45*P})}let b=t.signals??5;for(let i=0;i<b;i++){let u=Math.floor(o*.55+i*7.31),g=Math.floor(O(u,i*3.1+1.7)*h),f=Math.floor(O(u,i*5.7+4.2)*h);if(g===f)continue;let P=ct(o*.55+i*7.31),y=Q(r[g][0],r[f][0],P),D=Q(r[g][1],r[f][1],P),m=Q(r[g][2],r[f][2],P),w=Math.max(1e-6,Math.sqrt(y*y+D*D+m*m)),[v,z,k]=e(y/w,D/w,m/w),S=(k+1)/2;x.push({x:v,y:z,z:k,r:(R*1.5+p*S)*l,white:.05,a:.5+.5*S})}return B(x,M,t.rMin)},q={orbits:Bt,globe:vt,rubik:zt,wave:St,web:Ct,braid:wt,ribbon:st,ring:st,morph:At},Lt=Object.fromEntries(Object.entries(q).map(([n,o])=>[n,(t,a,c,s,e)=>j(t,o(a,c,e),s)])),lt={working:"orbits",searching:"globe",solving:"rubik",listening:"wave",connecting:"web",weaving:"braid",composing:"ribbon",breathing:"ring",shaping:"morph"},Ft={orbits:{64:{speed:1.885,count:1,size:1},32:{speed:2.9072,count:.4251,size:1.6849},20:{speed:3.9,count:.238,size:2.4}},globe:{64:{speed:2.015,count:.42,size:1.15,extra:{scanMul:4.08,dimBase:.45}},32:{speed:2.3803,count:.1839,size:1.4769,extra:{scanMul:4.2301,dimBase:.45}},20:{speed:2.665,count:.105,size:1.75,extra:{scanMul:4.335,dimBase:.45}}},rubik:{64:{speed:1.82,count:.35,size:1.05},32:{speed:1.8964,count:.1537,size:1.4951},20:{speed:1.95,count:.088,size:1.9}},wave:{64:{speed:4.388,count:.341,size:1},32:{speed:4.1512,count:.169,size:1.3232},20:{speed:3.998,count:.105,size:1.6}},web:{64:{speed:3.315,count:1.35,size:.95},32:{speed:5.0104,count:.4942,size:1.2571},20:{speed:6.63,count:.25,size:1.52}},braid:{64:{speed:1.625,count:.5,size:1},32:{speed:2.2234,count:.2056,size:1.2011},20:{speed:2.75,count:.1125,size:1.36}},ribbon:{64:{speed:2.34,count:.25,size:.85,extra:{spin:0,bandMul:3.9,wobMul:1}},32:{speed:2.7776,count:.0969,size:.9766,extra:{spin:0,bandMul:4.49,wobMul:1}},20:{speed:3.12,count:.051,size:1.073,extra:{spin:0,bandMul:4.94,wobMul:1}}},ring:{64:{speed:3.24,count:.25,size:.956,extra:{spin:0,bandMul:3.627,wobMul:.368}},32:{speed:3.5517,count:.0678,size:1.31,extra:{spin:0,bandMul:3.8265,wobMul:.4751}},20:{speed:3.78,count:.028,size:1.622,extra:{spin:0,bandMul:3.968,wobMul:.565}}},morph:{64:{speed:2.405,count:.702,size:.395,extra:{spread:1.45}},32:{speed:2.2057,count:.5937,size:.6916,extra:{spread:1.45}},20:{speed:2.08,count:.53,size:1.011,extra:{spread:1.45}}}},ot=new Map;function tt(n,o){let t=`${n}-${o}`,a=ot.get(t);if(a)return a;let c=lt[n],s=Ft[c][o],e={...yt[c]};s.count!==1&&(e=xt(e,s.count)),s.size!==1&&(e=gt(e,s.size)),s.extra&&(e={...e,...s.extra});let l={mode:c,speed:s.speed,opts:e};return ot.set(t,l),l}function Tt(n){var o=/^#([0-9a-f]{6})$/i.exec(n||"");if(o){var t=parseInt(o[1],16);return{r:t>>16&255,g:t>>8&255,b:t&255}}}window.LuOrb=function(n,o){o=o||{};var t=o.display||64,a=64,c=o.state||"breathing",s=o.color,e=!!o.dark,l=0,h=Math.min(2,window.devicePixelRatio||1),d=n.getContext("2d");n.width=Math.round(t*h),n.height=Math.round(t*h),n.style.width=t+"px",n.style.height=t+"px";var R=matchMedia("(prefers-reduced-motion: reduce)").matches,p;function r(){p=tt(c,a),p.fn=q[p.mode]}function M(b){var i=t/a;d.setTransform(h*i,0,0,h*i,0,0),d.clearRect(0,0,a,a),j(d,p.fn(a,b,p.opts),e,Tt(s))}function x(){M(performance.now()/1e3*p.speed),l=requestAnimationFrame(x)}return r(),R?M(.6):x(),{set:function(b,i){b&&(c=b),i!==void 0&&(s=i),r(),R&&M(.6)},stop:function(){cancelAnimationFrame(l)}}};})();

(function () {
  'use strict';
  if (window.LuScenes) return;
  var CSS = ":host{all:initial;}\n.ws{color:var(--ink);font-family:var(--font-b);}\n\n/* Layout: one screen, no page scroll. Column: brand line \u2192 dossier (what the visitor told us) \u2192 scene \u2192 live voice line.\n   The scene area is a size container; type grows with the screen. Cards keep natural height and sit centered.\n   Colors come from the client's brand (catalog.brand), not from the viewer theme. */\n:host {\n  color-scheme: light;\n  --paper: #f8f7f3; --ink: #0a0a0a; --muted: #55524f; --line: rgba(10,10,10,.14);\n  --accent: #e8694f; --accent-ink: #ffffff; --card: #ffffff; --glass: rgba(255,255,255,.82);\n  --ok: #0f7a52;\n  --bg-portrait: linear-gradient(160deg, #9c9692, #ec7d62);\n  --bg-landscape: linear-gradient(118deg, #9c9692, #ec7d62);\n  --font-d: \"Urbanist\", \"Onest\", Arial, sans-serif;\n  --font-b: \"Urbanist\", \"Onest\", Arial, sans-serif;\n  --r: 16px;\n}\n* { box-sizing: border-box; }\n[hidden] { display: none !important; }\n.ws { position: absolute; inset: 0; display: flex; flex-direction: column; gap: 10px; align-items: center;\n  padding: 12px max(16px, env(safe-area-inset-right, 0px)) 0 max(16px, env(safe-area-inset-left, 0px));\n  background: var(--bg-portrait); }\n@media (orientation: landscape) { .ws { background: var(--bg-landscape); } }\n.col { width: 100%; max-width: 1080px; }\n\n.top { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; }\n.brand { display: flex; align-items: center; gap: 9px; font: 700 15px/1 var(--font-d); color: var(--ink); letter-spacing: -.01em; }\n.brand img { height: 26px; width: auto; display: block; }\n.brand .mark { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; background: var(--ink); color: var(--paper); font: 800 11px/1 var(--font-d); }\n.escape { border: 1px solid var(--line); background: rgba(255,255,255,.55); color: var(--ink); border-radius: 10px; padding: 8px 12px; cursor: pointer; font: 600 12.5px/1 var(--font-b); white-space: nowrap; }\n.escape:hover { background: rgba(255,255,255,.8); }\n\n/* dossier: what we know about the visitor, written as text, not boxes */\n.dossier { flex: 0 0 auto; display: flex; gap: 6px 28px; flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid var(--line); min-height: 0; }\n.dossier:empty { display: none; }\n.dz { display: grid; gap: 3px; min-width: 0; animation: pop .4s ease both; }\n.dz span { font: 700 10.5px/1 var(--font-b); text-transform: uppercase; letter-spacing: .1em; color: var(--muted); }\n.dz b { font: 650 17px/1.25 var(--font-d); color: var(--ink); letter-spacing: -.01em; }\n\n.panel { position: relative; flex: 1 1 auto; min-height: 0; container-type: size; display: flex; }\n.scene { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; justify-content: safe center;\n  gap: 1em; font-size: clamp(12px, min(3cqh, 4.1cqw), 24px); padding-block: 6px; overflow-y: auto; scrollbar-width: none; }\n.scene::-webkit-scrollbar { display: none; }\n.h { margin: 0; font: 650 1.65em/1.08 var(--font-d); letter-spacing: -.03em; text-wrap: balance; }\n.sub { margin: 0; color: var(--ink); opacity: .75; font: 500 .95em/1.45 var(--font-b); max-width: 62ch; }\n.tag { font: 700 .66em/1 var(--font-b); letter-spacing: .1em; text-transform: uppercase; color: var(--accent); display: inline-flex; align-items: center; gap: .5em; }\n.tag::before { content: \"\"; width: .55em; height: .55em; border-radius: 50%; background: var(--accent); }\n.muted { color: var(--muted); }\n\n.card { position: relative; min-width: 0; background: var(--glass); border: 1px solid rgba(255,255,255,.7); border-radius: var(--r);\n  padding: 1.05em 1.15em; display: flex; flex-direction: column; gap: .6em; box-shadow: 0 10px 30px rgba(10,10,10,.07); overflow: hidden; }\n.card.hi { background: var(--card); border-color: var(--ink); box-shadow: 0 18px 44px rgba(10,10,10,.13); }\n.card h3 { margin: 0; font: 650 1.25em/1.15 var(--font-d); letter-spacing: -.02em; }\n.card p { margin: 0; color: var(--muted); font-size: .94em; line-height: 1.45; }\n.reason { font: 600 .98em/1.4 var(--font-b); color: var(--ink); padding-left: .8em; border-left: 3px solid var(--accent); }\n.list { margin: 0; padding: 0; list-style: none; display: grid; gap: .32em; font-size: .9em; line-height: 1.35; }\n.list li { padding-left: 1.25em; position: relative; }\n.list li::before { content: \"\u2713\"; position: absolute; left: 0; color: var(--ok); font-weight: 800; }\n.grid { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: clamp(8px, 1.4cqw, 16px); align-items: stretch; }\n\n/* welcome */\n.welcome { align-items: center; text-align: center; gap: 1.1em; }\n.welcome .wlogo { display: flex; align-items: center; gap: .6em; font: 700 1.15em/1 var(--font-d); }\n.welcome .wlogo img { height: 2.4em; width: auto; }\n.welcome .big { margin: 0; font: 700 2.7em/1.03 var(--font-d); letter-spacing: -.045em; max-width: 15ch; text-wrap: balance; }\n.welcome .lead { margin: 0; font: 500 1.08em/1.45 var(--font-b); max-width: 34ch; }\n.can { display: flex; flex-wrap: wrap; justify-content: center; gap: .3em 1.4em; padding-top: .6em; border-top: 1px solid var(--line); font: 600 .95em/1.6 var(--font-b); }\n.can span::before { content: \"\u2192 \"; color: var(--accent); }\n.say { font: 500 .95em/1.4 var(--font-b); }\n.say small { display: block; font: 700 .68em/1 var(--font-b); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: .4em; }\n\n/* plans */\n.tabs { display: flex; gap: 1.4em; border-bottom: 1px solid var(--line); align-self: flex-start; }\n.tabs button { border: 0; background: none; padding: .35em 0 .55em; margin-bottom: -1px; font: 650 .92em/1 var(--font-b); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }\n.tabs button[aria-pressed=\"true\"] { color: var(--ink); border-bottom-color: var(--ink); }\n.pname { font: 650 1.1em/1.2 var(--font-d); }\n.price { font: 750 2.2em/1 var(--font-d); letter-spacing: -.04em; font-variant-numeric: tabular-nums; white-space: nowrap; }\n.price small { font: 500 .38em/1 var(--font-b); color: var(--muted); letter-spacing: 0; }\n.save { font: 650 .82em/1.3 var(--font-b); color: var(--ok); }\n.kv { font-size: .88em; line-height: 1.35; }\n.kv b { font-variant-numeric: tabular-nums; }\n.pb { font: 650 .88em/1.3 var(--font-b); color: var(--ok); }\n.note { margin: 0; font-size: .8em; opacity: .75; }\n\n/* compare */\n.cmpt { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1fr) minmax(0, 1fr); background: var(--glass); border-radius: var(--r); border: 1px solid rgba(255,255,255,.7); overflow: hidden; box-shadow: 0 10px 30px rgba(10,10,10,.07); }\n.cmpt > div { padding: .7em .9em; border-top: 1px solid var(--line); font-size: .92em; min-width: 0; overflow-wrap: anywhere; }\n.cmpt > .hd { border-top: 0; padding-top: .9em; }\n.cmpt .k { color: var(--muted); font-size: .82em; }\n.cmpt .v { font-weight: 650; font-variant-numeric: tabular-nums; }\n.cmpt .rc { background: #fff; }\n.cmpt .hd .price { font-size: 1.7em; }\n.delta { margin: 0; font: 650 .95em/1.45 var(--font-b); }\n\n/* case, roi, booking */\n.case { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 1em; align-items: center; justify-items: center; text-align: center; }\n.case .num { font: 800 4.4em/1 var(--font-d); letter-spacing: -.05em; font-variant-numeric: tabular-nums; }\n.case .before .num { color: var(--muted); text-decoration: line-through; text-decoration-thickness: .06em; }\n.case .after .num { color: var(--accent); }\n.case .cap { font-size: .88em; color: var(--muted); margin-top: .3em; }\n.case .arrow { font: 600 2em/1 var(--font-d); color: var(--muted); }\n.roi { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: clamp(8px, 1.4cqw, 16px); align-items: center; }\n.ctl { display: grid; gap: .35em; }\n.ctl .row { display: flex; justify-content: space-between; gap: .6em; font: 600 .9em/1.2 var(--font-b); }\n.ctl .row b { font-variant-numeric: tabular-nums; white-space: nowrap; }\n.ctl input[type=range] { width: 100%; accent-color: var(--ink); margin: 0; }\n.out { background: var(--ink); color: var(--paper); border-radius: var(--r); padding: 1.1em 1.25em; display: grid; gap: .45em; box-shadow: 0 18px 44px rgba(10,10,10,.18); }\n.out .big span { display: block; font-size: .82em; opacity: .7; }\n.out .big b { font: 800 2.5em/1.05 var(--font-d); letter-spacing: -.04em; color: var(--accent); font-variant-numeric: tabular-nums; }\n.out .r { display: flex; justify-content: space-between; gap: .6em; font-size: .88em; }\n.out .r span { opacity: .7; }\n.out .r b { font-variant-numeric: tabular-nums; white-space: nowrap; }\n.book { display: grid; gap: .55em; width: 100%; max-width: 38em; align-self: center; }\n.brow { display: flex; justify-content: space-between; align-items: center; gap: .8em; padding: .8em 1em; border-radius: 12px; background: var(--glass); }\n.brow span { color: var(--muted); }\n.brow b { text-align: right; min-width: 0; }\n.ok { color: var(--ok); }\n.field { display: grid; gap: .35em; }\n.field label { font: 600 .82em/1.2 var(--font-b); color: var(--muted); }\n.field input { width: 100%; padding: .75em .9em; border: 1px solid var(--line); border-radius: 12px; background: var(--card); color: var(--ink); font: 500 max(16px, 1em)/1.2 var(--font-b); }\n.primary { border: 0; border-radius: 12px; min-height: 3em; padding: 0 1.5em; background: var(--ink); color: var(--paper); font: 650 1em/1 var(--font-b); cursor: pointer; }\n.narrowc { width: 100%; max-width: 38em; margin-inline: auto; }\n\n/* clients, trust, contacts */\n.logos { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(8px, 1.4cqw, 14px); }\n.logo { display: grid; place-items: center; text-align: center; min-height: 4.2em; padding: .8em; border-radius: 12px; background: var(--glass); font: 750 1.05em/1.15 var(--font-d); letter-spacing: -.02em; color: var(--ink); }\n.logo small { display: block; font: 600 .62em/1.2 var(--font-b); letter-spacing: .04em; color: var(--muted); margin-top: .35em; text-transform: uppercase; }\n.trust { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(8px, 1.4cqw, 14px); }\n.trust .card { flex-direction: row; align-items: flex-start; gap: .8em; }\n.trust svg { flex: 0 0 auto; width: 1.7em; height: 1.7em; stroke: var(--accent); fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }\n.trust h3 { font-size: 1.02em; margin-bottom: .25em; }\n.contacts { display: grid; gap: .5em; }\n.crow { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: .8em; padding: .75em 1em; border-radius: 12px; background: var(--glass); }\n.crow span { display: block; font-size: .8em; color: var(--muted); }\n.crow a, .crow b { font: 700 1.12em/1.25 var(--font-d); color: var(--ink); text-decoration: none; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }\n.copy { border: 1px solid var(--line); background: #fff; border-radius: 10px; padding: .5em .8em; font: 600 .8em/1 var(--font-b); cursor: pointer; color: var(--ink); }\n\n/* live voice line */\n.voice { flex: 0 0 auto; position: relative; display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; padding-bottom: calc(8px + env(safe-area-inset-bottom, 0px)); }\n.caption { min-height: 2.8em; font: 500 14px/1.4 var(--font-b); color: var(--ink); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }\n.caption b { font: 700 10.5px/1 var(--font-b); text-transform: uppercase; letter-spacing: .1em; color: var(--accent); margin-right: 8px; }\n.caption.you b { color: var(--muted); }\n#wave { width: 100%; height: 40px; display: block; }\n\n/* transitions: the shared card flies into its new place; everything else assembles from below */\n.scene.enter .in { animation: enter .62s cubic-bezier(.16,.84,.24,1) both; animation-delay: calc(var(--i, 0) * 70ms); }\n.scene.soft .in { animation: softin .3s ease both; }\n.card.hi::after { content: \"\"; position: absolute; inset: 0; pointer-events: none; background: linear-gradient(105deg, transparent 35%, rgba(255,255,255,.7) 50%, transparent 65%); transform: translateX(-120%); animation: sheen 1.1s .55s cubic-bezier(.3,.6,.3,1) both; }\n@keyframes softin { from { opacity: .45; } }\n@keyframes sheen { to { transform: translateX(120%); } }\n@keyframes pop { from { opacity: 0; transform: translateY(4px); } }\n@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }\n\n/* portrait screens: cards one under another, natural height, the group centered */\n@container (orientation: portrait) or (max-width: 640px) {\n  .scene { font-size: clamp(12px, min(2.15cqh, 4.6cqw), 22px); }\n  .grid { grid-auto-flow: row; grid-auto-rows: auto; }\n  .card.plan { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); column-gap: 1em; align-items: center; }\n  .card.plan .pl, .card.plan .pr { display: flex; flex-direction: column; gap: .3em; min-width: 0; }\n  .card.plan .reason { grid-column: 1 / -1; margin-top: .4em; }\n  .roi { grid-template-columns: minmax(0, 1fr); }\n  .roi .out { order: -1; }\n  .case { grid-template-columns: minmax(0, 1fr); gap: .3em; }\n  .case .arrow { transform: rotate(90deg); }\n  .trust { grid-template-columns: minmax(0, 1fr); }\n  .logos { grid-template-columns: repeat(3, minmax(0, 1fr)); }\n}\n@container ((orientation: portrait) or (max-width: 640px)) and (max-height: 600px) {\n  .card.svc .list, .card.plan .list, .welcome .can, .cmpt .opt { display: none; }\n  .card { padding: .8em .95em; }\n  .out .rows { display: grid; grid-template-columns: 1fr 1fr; gap: .3em 1em; }\n  .out .r { flex-direction: column; gap: .05em; font-size: .82em; }\n}\n@media (max-width: 640px) {\n  .dz b { font-size: 14.5px; }\n  .dossier { gap: 6px 18px; }\n  .caption { font-size: 13px; }\n}\n.ws { background-size: cover !important; background-position: center !important; }\n.dz b { font-size: clamp(15px, 1.55vw, 22px); }\n.meter { display: grid; gap: .3em; }\n.meter .bar { height: .45em; border-radius: 1em; background: rgba(10,10,10,.1); overflow: hidden; }\n.meter .bar i { display: block; height: 100%; border-radius: 1em; background: var(--ok); transform-origin: left; animation: grow .9s .25s cubic-bezier(.2,.8,.2,1) both; }\n.meter.over .bar i { background: #c2412d; }\n.meter .mt { display: flex; justify-content: space-between; gap: .5em; font: 600 .8em/1.25 var(--font-b); color: var(--muted); }\n.meter.over .mt b { color: #c2412d; }\n.meter.fit .mt b { color: var(--ok); }\n@keyframes grow { from { transform: scaleX(0); } }\n.plans3 { align-items: center; }\n.plans3 .card { gap: .5em; }\n.plans3 .card.hi { padding-block: 1.15em; }\n.badge { font: 700 .7em/1 var(--font-b); letter-spacing: .1em; text-transform: uppercase; display: inline-flex; align-items: center; gap: .45em; color: var(--accent); }\n.badge::before { content: \"\"; width: .55em; height: .55em; border-radius: 50%; background: currentColor; }\n.badge.pop { color: var(--muted); }\n.ptop { display: flex; justify-content: space-between; align-items: baseline; gap: .6em; flex-wrap: wrap; }\n.svc2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(8px, 1.4cqw, 16px); }\n.svcnum { font: 700 .72em/1 var(--font-b); color: var(--accent); letter-spacing: .08em; }\n.also { margin: 0; font: 500 .9em/1.6 var(--font-b); color: var(--ink); }\n.also b { font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; font-size: .78em; margin-right: .6em; }\n.also span + span::before { content: \" \u00b7 \"; color: var(--muted); }\n.head { display: grid; gap: .45em; }\n.cmpt .hd b.pname { display: block; }\n.cmpt .bad { color: #c2412d; }\n.cmpt .good { color: var(--ok); }\n.addr { font: 500 .9em/1.45 var(--font-b); }\n.soc { display: flex; flex-wrap: wrap; gap: .4em 1.4em; font: 650 .95em/1.4 var(--font-b); }\n.soc a { color: var(--ink); text-decoration: none; border-bottom: 1px solid var(--line); }\n.cgrid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: clamp(8px, 1.4cqw, 16px); align-items: center; }\n.morphing { animation: none !important; }\n/* scene change: old leaves, then blocks rise in order while their text types */\n.scene.leaving { transition: opacity .24s ease, transform .24s ease, filter .24s ease; opacity: 0; transform: translateY(-10px); filter: blur(4px); pointer-events: none; }\n.scene.enter .in { animation: rise .45s cubic-bezier(.2,.8,.2,1) both; animation-delay: calc(var(--i, 0) * 110ms); }\n@keyframes rise { from { opacity: 0; transform: translateY(14px); } }\n.cmpt, .crow, .logo, .out { position: relative; }\n.tag { display: block; }\n.tag::before { display: inline-block; margin-right: .55em; vertical-align: .12em; }\n#panel span.wd { display: inline !important; white-space: nowrap; margin: 0 !important; padding: 0 !important; color: inherit; font: inherit; letter-spacing: inherit; text-transform: inherit; opacity: 1; }\n#panel span.c { display: inline !important; margin: 0 !important; padding: 0 !important; color: inherit; font: inherit; letter-spacing: inherit; text-transform: inherit; opacity: 0; animation: ch .5s linear forwards; animation-delay: var(--d); }\n#panel span.wd::before, #panel span.c::before { content: none !important; }\n@keyframes ch { 0% { opacity: 1; color: var(--accent); } 100% { opacity: 1; } }\n@media (prefers-reduced-motion: reduce) { #panel span.c { opacity: 1 !important; } }\n.contacts { gap: .4em; }\n.crow { padding: .55em .9em; }\n.crow b { font-size: 1em; }\n.act { min-height: 2.2em; }\n.voice { display: flex; align-items: center; gap: 14px; }\n#orb { flex: 0 0 auto; display: block; }\n.vtext { min-width: 0; flex: 1 1 auto; display: grid; gap: 2px; }\n.vstate { min-height: 1.1em; font: 700 10.5px/1.1 var(--font-b); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }\n.logos { grid-template-columns: repeat(4, minmax(0, 1fr)); }\n.logo { background: #fff; min-height: 6em; padding: .9em 1.1em; overflow: hidden; }\n.logo img { display: block; max-width: 88%; max-height: 4.4em; width: auto; height: auto; object-fit: contain; }\n.logo .lsvg { display: block; width: 88%; max-width: 13em; }\n.logo .lsvg svg { display: block; width: 100%; height: auto; max-height: 3.4em; }\n.act { display: inline-flex; align-items: center; justify-content: center; min-height: 2.4em; padding: 0 1.1em; border-radius: 10px; font: 650 .88em/1 var(--font-b); text-decoration: none; white-space: nowrap; }\n.act.call { background: var(--ink); color: var(--paper); }\n.act.mail { background: var(--ink); color: var(--paper); }\n.crow b { font: 700 1.12em/1.25 var(--font-d); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }\n.k2 { display: block; font: 700 .7em/1 var(--font-b); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin: .9em 0 .5em; }\n.soc { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .5em; }\n.soc a { display: flex; align-items: center; gap: .55em; padding: .6em .75em; border: 0; border-radius: 10px; background: var(--ink); color: var(--paper); text-decoration: none; font: 650 .92em/1 var(--font-b); }\n.soc svg { width: 1.3em; height: 1.3em; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }\n@media (max-width: 640px) and (max-height: 720px) { .dz:nth-child(n+3) { display: none; } }\n.plans3 .card.side .list li:nth-child(n+3) { display: none; }\n.plans3 { font-size: .86em; grid-auto-columns: auto; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr) minmax(0, 1fr); }\n.col { max-width: 1320px; }\n.meter .mt { flex-wrap: wrap; }\n.cmpt { overflow: visible; font-size: .84em; }\n.cmpt > div { padding-block: .5em; }\n@container (max-height: 480px) { .cmpt .opt { display: none; } .cmpt > div { padding-block: .42em; } .cmpt > .hd { padding-top: .6em; } }\n.scene > .head.row { display: flex; justify-content: space-between; align-items: flex-end; gap: 1em; flex-wrap: wrap; }\n.dossier { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }\n.plans3 .card.hi .list { font-size: .86em; gap: .22em; }\n.tag { color: var(--ink); font-size: .74em; }\n.sub, .note { opacity: 1 !important; color: var(--ink); }\n.also b { color: var(--ink); opacity: .7; }\n.voice { background: rgba(255,255,255,.74); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); border-radius: 18px 18px 0 0; padding: 10px 16px calc(6px + env(safe-area-inset-bottom, 0px)); box-shadow: 0 -8px 30px rgba(10,10,10,.06); }\n.dossier { background: rgba(255,255,255,.5); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px); border: 0; border-radius: 14px; padding: 10px 16px; }\n.scene { font-size: clamp(13px, min(3.6cqh, 2.4cqw), 26px); }\n@container (orientation: portrait) or (max-width: 640px) { .scene { font-size: clamp(12px, min(2.7cqh, 5.1cqw), 22px); } }\n@media (max-width: 640px) {\n  .dossier { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px 14px; padding: 8px 12px; }\n  .dz b { font-size: 13.5px; line-height: 1.25; }\n  .dz span { font-size: 9.5px; }\n}\n@container (max-width: 380px) {\n  .card.plan.hi { grid-template-columns: minmax(0, 1fr); }\n}\n\n@container (orientation: portrait) or (max-width: 640px) {\n  .svc2 { grid-template-columns: minmax(0, 1fr); }\n  .cgrid { grid-template-columns: minmax(0, 1fr); }\n  .logos { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n  .soc { grid-template-columns: repeat(4, minmax(0, 1fr)); }\n  .soc a { flex-direction: column; gap: .35em; font-size: .78em; padding: .6em .3em; }\n  .contacts .crow span { font-size: .74em; }\n  .plans3 .card.side .list, .plans3 .card.side .kv { display: none; }\n  .plans3 .card.side { flex-direction: row; justify-content: space-between; align-items: center; padding: .8em 1.1em; }\n  .plans3 .card.side .meter { display: none; }\n  .plans3 { grid-template-columns: none; }\n}\n@container ((orientation: portrait) or (max-width: 640px)) and (max-height: 600px) {\n  .card.svc p { display: none; }\n  .plans3 .card.hi .list { display: none; }\n  .logo { min-height: 3em; }\n  .crow { padding: .55em .9em; }\n  .trust .card { padding: .7em .9em; }\n  .trust p { font-size: .84em; }\n  .cgrid .addr, .cgrid .k2 { display: none; }\n  .cgrid .card { padding: .6em; }\n  .logo { min-height: 3.6em; padding: .5em .8em; }\n  .logo img { max-height: 2.6em; }\n}\n.caption{display:none !important}\n.vstate{font:650 14px/1.3 var(--font-b);letter-spacing:0;text-transform:none;color:var(--ink);min-height:1.3em}\n.voice{min-height:64px}\n";
  /* Interface words of the scene layer. Catalog content (services, plans, clients…) comes already translated from the server. */
  var UI = {
    ru: { escape: "Не хочу говорить", activity: "Вид деятельности", problem: "Проблема", volume: "Объём", solution: "Решение",
      welcome: "Расскажите о задаче — я покажу решение", lead: "Говорите как обычно. Экран подстроится под вас.",
      can: ["Подберу решение под вашу задачу", "Посчитаю выгоду в ваших цифрах", "Запишу на встречу"],
      svcH: "Как мы это решаем", also: "Ещё делаем",
      plH: "Цены и тарифы", month: "В месяц", year: "За год", perMonth: "/ мес", from: "от", rec: "Для вас", popular: "Выбирают чаще",
      needOf: "Нужно {a} из {b}", over: "не хватит", fit: "хватает с запасом", save: "Экономия {v} в год",
      approx: "≈ {m} мин разговоров или {d} диалогов", trial: "Пробный период — {d} дней бесплатно, без карты.",
      cmpH: "{a} или {b}", kPrice: "В месяц", kYear: "При оплате за год", kVoice: "Минут голосом", kChat: "Диалогов в чате", kYour: "Ваш объём",
      kUsers: "Пользователи", kKeep: "Хранение записей", kBranches: "Филиалы", kSupport: "Поддержка", kPayback: "Окупаемость",
      months: "{v} мес", unlim: "без лимита", enough: "хватает", notEnough: "не хватит", days: "{v} дн.",
      delta: "Разница — {p} в месяц.",
      roiH: "Расчёт выгоды", missed: "Пропущено обращений в месяц", leadV: "Средний чек", cap: "Вернёт агент",
      recovered: "Вернёте обращений", gross: "Дополнительная выручка", cost: "Тариф {p}", net: "Чистая выгода в месяц", payback: "Окупаемость",
      caseH: "Как это было у похожего клиента", example: "Пример — заменим реальным кейсом",
      clientsH: "С нами уже работают", trustH: "Безопасно и по правилам",
      contH: "Позвонить или написать самому", call: "Позвонить", write: "Написать", follow: "Мы в соцсетях",
      ended: "Разговор на сайте завершён",
      bookH: "Проверьте запись", bookSub: "Если всё верно — скажите «да» или нажмите.", name: "Имя", phone: "Телефон", time: "Дата и время", task: "Задача",
      verified: "подтверждён", confirm: "Подтвердить запись", confirmed: "Готово, записываю",
      agent: "Ассистент", you: "Вы", listening: "Слушаю" },
    ro: { escape: "Nu vreau să vorbesc", activity: "Domeniu de activitate", problem: "Problema", volume: "Volum", solution: "Soluția",
      welcome: "Spuneți-mi sarcina — vă arăt soluția", lead: "Vorbiți firesc. Ecranul se adaptează la dvs.",
      can: ["Aleg soluția pentru sarcina dvs.", "Calculez câștigul în cifrele dvs.", "Vă programez la o întâlnire"],
      svcH: "Cum rezolvăm", also: "Mai facem",
      plH: "Prețuri și planuri", month: "Lunar", year: "Anual", perMonth: "/ lună", from: "de la", rec: "Pentru dvs.", popular: "Cel mai ales",
      needOf: "Necesar {a} din {b}", over: "nu ajunge", fit: "ajunge cu rezervă", save: "Economie {v} pe an",
      approx: "≈ {m} min de convorbiri sau {d} dialoguri", trial: "Perioadă de probă — {d} zile gratuit, fără card.",
      cmpH: "{a} sau {b}", kPrice: "Pe lună", kYear: "La plata anuală", kVoice: "Minute vocal", kChat: "Dialoguri în chat", kYour: "Volumul dvs.",
      kUsers: "Utilizatori", kKeep: "Păstrarea înregistrărilor", kBranches: "Filiale", kSupport: "Suport", kPayback: "Recuperare",
      months: "{v} luni", unlim: "nelimitat", enough: "ajunge", notEnough: "nu ajunge", days: "{v} zile",
      delta: "Diferența — {p} pe lună.",
      roiH: "Calculul câștigului", missed: "Solicitări pierdute pe lună", leadV: "Valoarea medie", cap: "Recuperează agentul",
      recovered: "Solicitări recuperate", gross: "Venit suplimentar", cost: "Planul {p}", net: "Câștig net pe lună", payback: "Recuperare",
      caseH: "Cum a fost la un client asemănător", example: "Exemplu — îl înlocuim cu un caz real",
      clientsH: "Lucrează deja cu noi", trustH: "Sigur și după reguli",
      contH: "Sunați sau scrieți direct", call: "Sunați", write: "Scrieți", follow: "Suntem pe rețele",
      ended: "Convorbirea pe site s-a încheiat",
      bookH: "Verificați programarea", bookSub: "Dacă totul e corect — spuneți „da” sau apăsați.", name: "Nume", phone: "Telefon", time: "Data și ora", task: "Scop",
      verified: "confirmat", confirm: "Confirmă programarea", confirmed: "Gata, vă programez",
      agent: "Asistent", you: "Dvs.", listening: "Ascult" },
    en: { escape: "I don't want to talk", activity: "Business type", problem: "Problem", volume: "Volume", solution: "Solution",
      welcome: "Tell me your task — I'll show you the solution", lead: "Just talk. The screen adapts to you.",
      can: ["I pick the solution for your task", "I estimate the gain in your numbers", "I book you a meeting"],
      svcH: "How we solve it", also: "We also do",
      plH: "Prices and plans", month: "Monthly", year: "Yearly", perMonth: "/ mo", from: "from", rec: "For you", popular: "Most chosen",
      needOf: "Need {a} of {b}", over: "not enough", fit: "fits with headroom", save: "Save {v} a year",
      approx: "≈ {m} min of calls or {d} chats", trial: "Trial — {d} days free, no card.",
      cmpH: "{a} or {b}", kPrice: "Per month", kYear: "Paid yearly", kVoice: "Voice minutes", kChat: "Chat dialogs", kYour: "Your volume",
      kUsers: "Users", kKeep: "Recording retention", kBranches: "Branches", kSupport: "Support", kPayback: "Payback",
      months: "{v} mo", unlim: "unlimited", enough: "fits", notEnough: "not enough", days: "{v} days",
      delta: "The difference is {p} a month.",
      roiH: "Your gain estimate", missed: "Missed requests a month", leadV: "Average order", cap: "Agent recovers",
      recovered: "Requests recovered", gross: "Extra revenue", cost: "{p} plan", net: "Net gain a month", payback: "Payback",
      caseH: "How it went for a similar client", example: "Example — to be replaced with a real case",
      clientsH: "Already working with us", trustH: "Safe and by the rules",
      contH: "Call or write yourself", call: "Call", write: "Write", follow: "Follow us",
      ended: "Site conversation ended",
      bookH: "Check your booking", bookSub: "If it's right — say “yes” or tap.", name: "Name", phone: "Phone", time: "Date and time", task: "Purpose",
      verified: "verified", confirm: "Confirm booking", confirmed: "Done, booking",
      agent: "Assistant", you: "You", listening: "Listening" },
    fr: { escape: "Je ne veux pas parler", activity: "Activité", problem: "Problème", volume: "Volume", solution: "Solution",
      welcome: "Décrivez votre besoin — je vous montre la solution", lead: "Parlez naturellement. L'écran s'adapte à vous.",
      can: ["Je choisis la solution adaptée", "Je calcule le gain avec vos chiffres", "Je vous fixe un rendez-vous"],
      svcH: "Comment nous le résolvons", also: "Nous faisons aussi",
      plH: "Prix et offres", month: "Mensuel", year: "Annuel", perMonth: "/ mois", from: "dès", rec: "Pour vous", popular: "Le plus choisi",
      needOf: "Besoin {a} sur {b}", over: "insuffisant", fit: "suffit avec marge", save: "Économie de {v} par an",
      approx: "≈ {m} min d'appels ou {d} conversations", trial: "Essai — {d} jours gratuits, sans carte.",
      cmpH: "{a} ou {b}", kPrice: "Par mois", kYear: "Paiement annuel", kVoice: "Minutes vocales", kChat: "Conversations chat", kYour: "Votre volume",
      kUsers: "Utilisateurs", kKeep: "Conservation des enregistrements", kBranches: "Filiales", kSupport: "Support", kPayback: "Rentabilité",
      months: "{v} mois", unlim: "illimité", enough: "suffit", notEnough: "insuffisant", days: "{v} j",
      delta: "La différence : {p} par mois.",
      roiH: "Estimation du gain", missed: "Demandes manquées par mois", leadV: "Panier moyen", cap: "Récupéré par l'agent",
      recovered: "Demandes récupérées", gross: "Chiffre d'affaires en plus", cost: "Offre {p}", net: "Gain net par mois", payback: "Rentabilité",
      caseH: "Comment cela s'est passé chez un client similaire", example: "Exemple — sera remplacé par un cas réel",
      clientsH: "Ils travaillent déjà avec nous", trustH: "Sûr et dans les règles",
      contH: "Appeler ou écrire directement", call: "Appeler", write: "Écrire", follow: "Suivez-nous",
      ended: "Conversation sur le site terminée",
      bookH: "Vérifiez le rendez-vous", bookSub: "Si tout est correct — dites « oui » ou appuyez.", name: "Nom", phone: "Téléphone", time: "Date et heure", task: "Objet",
      verified: "vérifié", confirm: "Confirmer le rendez-vous", confirmed: "C'est noté",
      agent: "Assistante", you: "Vous", listening: "J'écoute" },
    it: { escape: "Non voglio parlare", activity: "Settore", problem: "Problema", volume: "Volume", solution: "Soluzione",
      welcome: "Raccontami il tuo obiettivo — ti mostro la soluzione", lead: "Parla normalmente. Lo schermo si adatta a te.",
      can: ["Scelgo la soluzione giusta", "Calcolo il guadagno con i tuoi numeri", "Ti fisso un incontro"],
      svcH: "Come lo risolviamo", also: "Facciamo anche",
      plH: "Prezzi e piani", month: "Mensile", year: "Annuale", perMonth: "/ mese", from: "da", rec: "Per te", popular: "Il più scelto",
      needOf: "Servono {a} su {b}", over: "non basta", fit: "basta con margine", save: "Risparmi {v} all'anno",
      approx: "≈ {m} min di chiamate o {d} conversazioni", trial: "Prova — {d} giorni gratis, senza carta.",
      cmpH: "{a} o {b}", kPrice: "Al mese", kYear: "Pagamento annuale", kVoice: "Minuti voce", kChat: "Conversazioni chat", kYour: "Il tuo volume",
      kUsers: "Utenti", kKeep: "Conservazione registrazioni", kBranches: "Filiali", kSupport: "Assistenza", kPayback: "Rientro",
      months: "{v} mesi", unlim: "illimitato", enough: "basta", notEnough: "non basta", days: "{v} giorni",
      delta: "La differenza è di {p} al mese.",
      roiH: "Stima del guadagno", missed: "Richieste perse al mese", leadV: "Scontrino medio", cap: "Recupera l'agente",
      recovered: "Richieste recuperate", gross: "Ricavi in più", cost: "Piano {p}", net: "Guadagno netto al mese", payback: "Rientro",
      caseH: "Com'è andata con un cliente simile", example: "Esempio — sarà sostituito da un caso reale",
      clientsH: "Lavorano già con noi", trustH: "Sicuro e secondo le regole",
      contH: "Chiama o scrivi direttamente", call: "Chiama", write: "Scrivi", follow: "Seguici",
      ended: "Conversazione sul sito terminata",
      bookH: "Controlla la prenotazione", bookSub: "Se è tutto giusto — di' «sì» o tocca.", name: "Nome", phone: "Telefono", time: "Data e ora", task: "Scopo",
      verified: "verificato", confirm: "Conferma prenotazione", confirmed: "Fatto, prenoto",
      agent: "Assistente", you: "Tu", listening: "Ascolto" },
    pl: { escape: "Nie chcę rozmawiać", activity: "Branża", problem: "Problem", volume: "Skala", solution: "Rozwiązanie",
      welcome: "Opowiedz o zadaniu — pokażę rozwiązanie", lead: "Mów normalnie. Ekran dopasuje się do Ciebie.",
      can: ["Dobiorę rozwiązanie do zadania", "Policzę zysk na Twoich liczbach", "Umówię spotkanie"],
      svcH: "Jak to rozwiązujemy", also: "Robimy też",
      plH: "Ceny i plany", month: "Miesięcznie", year: "Rocznie", perMonth: "/ mies.", from: "od", rec: "Dla Ciebie", popular: "Najczęściej wybierany",
      needOf: "Potrzeba {a} z {b}", over: "nie wystarczy", fit: "wystarczy z zapasem", save: "Oszczędność {v} rocznie",
      approx: "≈ {m} min rozmów lub {d} czatów", trial: "Okres próbny — {d} dni za darmo, bez karty.",
      cmpH: "{a} czy {b}", kPrice: "Miesięcznie", kYear: "Przy płatności rocznej", kVoice: "Minuty głosowe", kChat: "Rozmowy na czacie", kYour: "Twoja skala",
      kUsers: "Użytkownicy", kKeep: "Przechowywanie nagrań", kBranches: "Oddziały", kSupport: "Wsparcie", kPayback: "Zwrot",
      months: "{v} mies.", unlim: "bez limitu", enough: "wystarczy", notEnough: "nie wystarczy", days: "{v} dni",
      delta: "Różnica — {p} miesięcznie.",
      roiH: "Szacunek zysku", missed: "Utracone zgłoszenia miesięcznie", leadV: "Średnia wartość", cap: "Odzyska agent",
      recovered: "Odzyskane zgłoszenia", gross: "Dodatkowy przychód", cost: "Plan {p}", net: "Zysk netto miesięcznie", payback: "Zwrot",
      caseH: "Jak to wyglądało u podobnego klienta", example: "Przykład — zastąpimy prawdziwym case study",
      clientsH: "Już z nami pracują", trustH: "Bezpiecznie i zgodnie z zasadami",
      contH: "Zadzwoń lub napisz sam", call: "Zadzwoń", write: "Napisz", follow: "Jesteśmy w sieci",
      ended: "Rozmowa na stronie zakończona",
      bookH: "Sprawdź rezerwację", bookSub: "Jeśli wszystko się zgadza — powiedz „tak” lub kliknij.", name: "Imię", phone: "Telefon", time: "Data i godzina", task: "Cel",
      verified: "potwierdzony", confirm: "Potwierdź rezerwację", confirmed: "Gotowe, zapisuję",
      agent: "Asystentka", you: "Ty", listening: "Słucham" },
    uk: { escape: "Не хочу говорити", activity: "Вид діяльності", problem: "Проблема", volume: "Обсяг", solution: "Рішення",
      welcome: "Розкажіть про задачу — я покажу рішення", lead: "Говоріть як зазвичай. Екран підлаштується під вас.",
      can: ["Підберу рішення під вашу задачу", "Порахую вигоду у ваших цифрах", "Запишу на зустріч"],
      svcH: "Як ми це вирішуємо", also: "Ще робимо",
      plH: "Ціни й тарифи", month: "Щомісяця", year: "За рік", perMonth: "/ міс", from: "від", rec: "Для вас", popular: "Обирають частіше",
      needOf: "Потрібно {a} з {b}", over: "не вистачить", fit: "вистачає із запасом", save: "Економія {v} на рік",
      approx: "≈ {m} хв розмов або {d} діалогів", trial: "Пробний період — {d} днів безкоштовно, без картки.",
      cmpH: "{a} чи {b}", kPrice: "На місяць", kYear: "При оплаті за рік", kVoice: "Хвилин голосом", kChat: "Діалогів у чаті", kYour: "Ваш обсяг",
      kUsers: "Користувачі", kKeep: "Зберігання записів", kBranches: "Філії", kSupport: "Підтримка", kPayback: "Окупність",
      months: "{v} міс", unlim: "без ліміту", enough: "вистачає", notEnough: "не вистачить", days: "{v} дн.",
      delta: "Різниця — {p} на місяць.",
      roiH: "Розрахунок вигоди", missed: "Пропущено звернень на місяць", leadV: "Середній чек", cap: "Поверне агент",
      recovered: "Повернете звернень", gross: "Додатковий виторг", cost: "Тариф {p}", net: "Чиста вигода на місяць", payback: "Окупність",
      caseH: "Як це було в схожого клієнта", example: "Приклад — замінимо реальним кейсом",
      clientsH: "З нами вже працюють", trustH: "Безпечно й за правилами",
      contH: "Зателефонувати або написати самому", call: "Зателефонувати", write: "Написати", follow: "Ми в соцмережах",
      ended: "Розмову на сайті завершено",
      bookH: "Перевірте запис", bookSub: "Якщо все правильно — скажіть «так» або натисніть.", name: "Ім'я", phone: "Телефон", time: "Дата й час", task: "Задача",
      verified: "підтверджено", confirm: "Підтвердити запис", confirmed: "Готово, записую",
      agent: "Асистентка", you: "Ви", listening: "Слухаю" },
    pt: { escape: "Não quero falar", activity: "Área de atividade", problem: "Problema", volume: "Volume", solution: "Solução",
      welcome: "Conte-me a sua necessidade — eu mostro a solução", lead: "Fale naturalmente. O ecrã adapta-se a si.",
      can: ["Escolho a solução certa", "Calculo o ganho com os seus números", "Marco-lhe uma reunião"],
      svcH: "Como resolvemos", also: "Também fazemos",
      plH: "Preços e planos", month: "Mensal", year: "Anual", perMonth: "/ mês", from: "desde", rec: "Para si", popular: "O mais escolhido",
      needOf: "Precisa de {a} de {b}", over: "não chega", fit: "chega com folga", save: "Poupança de {v} por ano",
      approx: "≈ {m} min de chamadas ou {d} conversas", trial: "Teste — {d} dias grátis, sem cartão.",
      cmpH: "{a} ou {b}", kPrice: "Por mês", kYear: "Pagamento anual", kVoice: "Minutos de voz", kChat: "Conversas de chat", kYour: "O seu volume",
      kUsers: "Utilizadores", kKeep: "Arquivo de gravações", kBranches: "Filiais", kSupport: "Suporte", kPayback: "Retorno",
      months: "{v} meses", unlim: "ilimitado", enough: "chega", notEnough: "não chega", days: "{v} dias",
      delta: "A diferença é de {p} por mês.",
      roiH: "Estimativa de ganho", missed: "Pedidos perdidos por mês", leadV: "Valor médio", cap: "Recupera o agente",
      recovered: "Pedidos recuperados", gross: "Receita extra", cost: "Plano {p}", net: "Ganho líquido por mês", payback: "Retorno",
      caseH: "Como correu com um cliente semelhante", example: "Exemplo — será substituído por um caso real",
      clientsH: "Já trabalham connosco", trustH: "Seguro e dentro das regras",
      contH: "Ligar ou escrever diretamente", call: "Ligar", write: "Escrever", follow: "Siga-nos",
      ended: "Conversa no site terminada",
      bookH: "Verifique a marcação", bookSub: "Se estiver certo — diga «sim» ou toque.", name: "Nome", phone: "Telefone", time: "Data e hora", task: "Objetivo",
      verified: "verificado", confirm: "Confirmar marcação", confirmed: "Feito, a marcar",
      agent: "Assistente", you: "Você", listening: "A ouvir" },
    cs: { escape: "Nechci mluvit", activity: "Obor", problem: "Problém", volume: "Objem", solution: "Řešení",
      welcome: "Řekněte mi, co potřebujete — ukážu řešení", lead: "Mluvte normálně. Obrazovka se vám přizpůsobí.",
      can: ["Vyberu řešení pro váš úkol", "Spočítám přínos ve vašich číslech", "Domluvím schůzku"],
      svcH: "Jak to řešíme", also: "Děláme také",
      plH: "Ceny a tarify", month: "Měsíčně", year: "Ročně", perMonth: "/ měs.", from: "od", rec: "Pro vás", popular: "Nejčastější volba",
      needOf: "Potřeba {a} z {b}", over: "nestačí", fit: "stačí s rezervou", save: "Úspora {v} ročně",
      approx: "≈ {m} min hovorů nebo {d} chatů", trial: "Zkušební doba — {d} dní zdarma, bez karty.",
      cmpH: "{a} nebo {b}", kPrice: "Měsíčně", kYear: "Při roční platbě", kVoice: "Minuty hlasu", kChat: "Konverzace v chatu", kYour: "Váš objem",
      kUsers: "Uživatelé", kKeep: "Uchování nahrávek", kBranches: "Pobočky", kSupport: "Podpora", kPayback: "Návratnost",
      months: "{v} měs.", unlim: "bez limitu", enough: "stačí", notEnough: "nestačí", days: "{v} dní",
      delta: "Rozdíl je {p} měsíčně.",
      roiH: "Odhad přínosu", missed: "Zmeškané poptávky za měsíc", leadV: "Průměrná objednávka", cap: "Agent vrátí",
      recovered: "Vrácené poptávky", gross: "Tržby navíc", cost: "Tarif {p}", net: "Čistý přínos za měsíc", payback: "Návratnost",
      caseH: "Jak to šlo u podobného klienta", example: "Příklad — nahradíme skutečnou případovou studií",
      clientsH: "Už s námi pracují", trustH: "Bezpečně a podle pravidel",
      contH: "Zavolat nebo napsat sami", call: "Zavolat", write: "Napsat", follow: "Sledujte nás",
      ended: "Rozhovor na webu skončil",
      bookH: "Zkontrolujte rezervaci", bookSub: "Pokud je vše správně — řekněte „ano“ nebo klepněte.", name: "Jméno", phone: "Telefon", time: "Datum a čas", task: "Účel",
      verified: "ověřeno", confirm: "Potvrdit rezervaci", confirmed: "Hotovo, zapisuji",
      agent: "Asistentka", you: "Vy", listening: "Poslouchám" }
  };

  /* ===== Scene layer: full-screen view over the client's site, isolated in a shadow root ===== */
  var host = null, root = null, cfg = { catalog: null, lang: "en", base: "", on: {} };
  var st = { scene: "", args: {}, profile: {}, billing: "month", roi: null, open: false, agent: "", orb: null, orbRest: 0, prevOverflow: "" };
  var showSeq = 0;

  function $(id) { return root ? root.getElementById(id) : null; }
  function T(k, vars) {
    var d = UI[cfg.lang] || UI.en, s = d[k]; if (s == null) s = UI.en[k]; if (s == null) s = k;
    if (vars && typeof s === "string") Object.keys(vars).forEach(function (x) { s = s.split("{" + x + "}").join(vars[x]); });
    return s;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function url(u) { u = String(u || ""); return /^(https?:|data:|file:|blob:)/.test(u) ? u : cfg.base + (u.charAt(0) === "/" ? "" : "/") + u; }
  function C() { return cfg.catalog || {}; }
  function loc() { return ({ ru: "ru-RU", ro: "ro-RO", en: "en-GB", fr: "fr-FR", it: "it-IT", pl: "pl-PL", uk: "uk-UA", pt: "pt-PT", cs: "cs-CZ" })[cfg.lang] || "en-GB"; }
  function money(v) { try { return new Intl.NumberFormat(loc(), { style: "currency", currency: C().currency || "EUR", maximumFractionDigits: 0 }).format(v); } catch (e) { return Math.round(v) + " €"; } }
  function num(v) { try { return new Intl.NumberFormat(loc()).format(Math.round(v)); } catch (e) { return String(Math.round(v)); } }
  function plans() { var p = C().plans; return (p && p.items) || (Array.isArray(p) ? p : []); }
  function plansCfg() { var p = C().plans; return p && !Array.isArray(p) ? p : {}; }
  function texts() { return C().texts || {}; }
  function TX(key, def) { var v = texts()[key]; return v == null || v === "" ? def : v; }
  function plan(id) { return plans().filter(function (p) { return p.id === id; })[0]; }
  function price(p) { return st.billing === "year" && p.year ? p.year : p.month; }
  function round(v) { var m = v >= 1000 ? 100 : 10; return Math.round(v / m) * m; }
  /* calculator formulas: numbers, input ids, plan_price, + - * / and brackets — nothing else is evaluated */
  function calc(expr, vars) {
    var toks = String(expr || "").match(/\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*|[-+*/()]/g) || [], i = 0;
    function peek() { return toks[i]; }
    function atom() {
      var t = toks[i++];
      if (t === "(") { var v = sum(); i++; return v; }
      if (t === "-") return -atom();
      if (/^\d/.test(t)) return parseFloat(t);
      var v2 = vars[t]; return typeof v2 === "number" ? v2 : NaN;
    }
    function prod() { var v = atom(); while (peek() === "*" || peek() === "/") { var op = toks[i++], r = atom(); v = op === "*" ? v * r : v / r; } return v; }
    function sum() { var v = prod(); while (peek() === "+" || peek() === "-") { var op = toks[i++], r = prod(); v = op === "+" ? v + r : v - r; } return v; }
    var out = sum(); return isFinite(out) ? out : NaN;
  }
  function calcCfg() { return C().calculator || null; }
  function calcVars(p) {
    var v = { plan_price: p ? price(p) : 0 }, k = calcCfg(); if (!k) return v;
    (k.inputs || []).forEach(function (inp) { v[inp.id] = st.roi && st.roi[inp.id] != null ? +st.roi[inp.id] : +inp["default"] || 0; });
    return v;
  }
  function paybackDays(p) {
    var k = calcCfg(); if (!k || !st.roi) return 0;
    var o = (k.outputs || []).filter(function (x) { return x.payback; })[0]; if (!o) return 0;
    var d = calc(o.expr, calcVars(p)); return isFinite(d) && d > 0 ? Math.max(1, Math.ceil(d)) : 0;
  }
  function fmtOut(v, f) {
    if (!isFinite(v)) return "—";
    if (f === "money") return money(v);
    if (f === "money_minus") return "− " + money(Math.abs(v));
    if (f === "percent") return Math.round(v) + "%";
    if (f === "days") return v > 0 ? T("days", { v: Math.max(1, Math.ceil(v)) }) : "—";
    return num(v);
  }

  /* ----- scenes ----- */
  function sceneWelcome() {
    var b = C().brand || {};
    return '<div class="scene welcome">' +
      '<div class="wlogo in">' + (b.logo ? '<img src="' + esc(url(b.logo)) + '" alt="">' : '') + '<span>' + esc(b.name || "") + '</span></div>' +
      '<h1 class="big in">' + esc(TX("welcome_title", T("welcome"))) + '</h1>' +
      '<p class="lead in">' + esc(TX("welcome_lead", T("lead"))) + '</p>' +
      ((texts().welcome_points || []).length ? '<div class="can in">' + texts().welcome_points.map(function (c) { return "<span>" + esc(c) + "</span>"; }).join("") + '</div>' : '') + '</div>';
  }
  function sceneServices(a) {
    var all = C().services || [], hi = (a.highlight || []).filter(function (id) { return all.some(function (s) { return s.id === id; }); }), reasons = a.reasons || {};
    if (!hi.length) hi = all.slice(0, 2).map(function (s) { return s.id; });
    var top = hi.map(function (id) { return all.filter(function (s) { return s.id === id; })[0]; });
    var rest = all.filter(function (s) { return hi.indexOf(s.id) < 0; });
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(TX("services_title", T("svcH"))) + '</span></div>' +
      '<div class="svc2">' + top.map(function (s, i) {
        return '<article class="card svc in' + (i === 0 ? " hi" : "") + '" data-morph="svc-' + esc(s.id) + '"><span class="svcnum">0' + (i + 1) + '</span><h3>' + esc(s.title) + '</h3><p>' + esc(s.short) + '</p>' +
          (reasons[s.id] ? '<div class="reason">' + esc(reasons[s.id]) + '</div>' : '') + '</article>';
      }).join("") + '</div>' +
      (rest.length ? '<p class="also in"><b>' + esc(T("also")) + '</b>' + rest.map(function (s) { return "<span>" + esc(s.title) + "</span>"; }).join("") + '</p>' : '') + '</div>';
  }
  function meter(p, need, fits) {
    if (!need || !p.capacity) return "";
    var k = need / p.capacity, ok = fits ? fits[p.id] !== false : k <= 1, unit = (plansCfg().picker || {}).unit || "";
    return '<div class="meter ' + (ok ? "fit" : "over") + '"><div class="bar"><i style="width:' + Math.min(100, Math.round(k * 100)) + '%"></i></div>' +
      '<div class="mt"><span>' + esc(T("needOf", { a: num(round(need)), b: num(p.capacity) + (unit ? " " + unit : "") })) + '</span><b>' + esc(ok ? T("fit") : T("over")) + '</b></div></div>';
  }
  function planCard(p, rec, reason, need, fits) {
    var saveV = p.year ? (p.month - p.year) * 12 : 0;
    return '<article class="card plan in ' + (rec ? "hi" : "side") + '" data-morph="plan-' + esc(p.id) + '">' +
      '<div class="pl"><div class="ptop">' + (rec ? '<span class="badge">' + esc(T("rec")) + '</span>' : p.popular ? '<span class="badge pop">' + esc(T("popular")) + '</span>' : '') + '</div>' +
      '<div class="pname">' + esc(p.name) + '</div></div>' +
      '<div class="pr"><div class="price">' + (p.from ? '<small>' + esc(T("from")) + ' </small>' : '') + esc(money(price(p))) + ' <small>' + esc(T("perMonth")) + '</small></div>' +
      (st.billing === "year" && saveV ? '<div class="save">' + esc(T("save", { v: money(saveV) })) + '</div>' : '') +
      (p.highlight ? '<div class="kv">' + esc(p.highlight) + '</div>' : '') + '</div>' +
      meter(p, need, fits) +
      '<ul class="list">' + (p.features || []).map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + (p.annual && rec ? "<li>" + esc(p.annual) + "</li>" : "") + '</ul>' +
      (rec && reason ? '<div class="reason">' + esc(reason) + '</div>' : '') + '</article>';
  }
  function scenePlans(a) {
    var ids = plans().map(function (p) { return p.id; }), rec = plan(a.rec) ? a.rec : (plans().filter(function (p) { return p.popular; })[0] || plans()[0] || {}).id;
    var i = ids.indexOf(rec), pick = [ids[Math.max(0, i - 1)], ids[i], ids[Math.min(ids.length - 1, i + 1)]].filter(function (x, k, arr) { return x && arr.indexOf(x) === k; });
    var note = plansCfg().note, hasYear = plans().some(function (p) { return p.year; });
    return '<div class="scene"><div class="head row in"><span class="tag">' + esc(TX("plans_title", T("plH"))) + '</span>' + (!hasYear ? '</div>' :
      '<div class="tabs" role="group"><button type="button" data-bill="month" aria-pressed="' + (st.billing === "month") + '">' + esc(T("month")) + '</button><button type="button" data-bill="year" aria-pressed="' + (st.billing === "year") + '">' + esc(T("year")) + '</button></div></div>') +
      '<div class="grid plans3">' + pick.map(function (id) { return planCard(plan(id), id === rec, a.reason, a.need, a.fits); }).join("") + '</div>' +
      (note ? '<p class="note in">' + esc(note) + '</p>' : '') + '</div>';
  }
  function sceneCompare(a) {
    var A = plan(a.a), B = plan(a.b); if (!A || !B) return scenePlans(a);
    var need = a.need || 0, fits = a.fits || {};
    function cell(p, row) {
      var v = (p.limits || {})[row.key];
      if (v === 0) return esc(T("unlim"));
      if (typeof v === "number") return num(v);
      return v == null || v === "" ? "—" : esc(v);
    }
    var rows = [];
    if (A.year || B.year) rows.push({ k: T("kYear"), v: function (p) { return p.year ? esc(money(p.year)) + " " + esc(T("perMonth")) : "—"; } });
    if (need) rows.push({ k: T("kYour"), v: function (p) { var ok = fits[p.id] !== false; return '<span class="' + (ok ? "good" : "bad") + '">' + esc(ok ? T("enough") : T("notEnough")) + '</span>'; } });
    (plansCfg().compare_rows || []).forEach(function (r) { rows.push({ k: r.label, opt: r.optional, v: function (p) { return cell(p, r); } }); });
    if (st.roi && paybackDays(A)) rows.push({ k: T("kPayback"), v: function (p) { var d = paybackDays(p); return d ? esc(T("days", { v: d })) : "—"; } });
    var html = '<div class="hd k">' + esc(T("kPrice")) + '</div>' +
      '<div class="hd" data-morph="plan-' + esc(A.id) + '"><b class="pname">' + esc(A.name) + '</b><span class="price">' + esc(money(A.month)) + '</span></div>' +
      '<div class="hd rc" data-morph="plan-' + esc(B.id) + '"><b class="pname">' + esc(B.name) + '</b><span class="price">' + esc(money(B.month)) + '</span></div>';
    rows.forEach(function (r) { var o = r.opt ? " opt" : ""; html += '<div class="k' + o + '">' + esc(r.k) + '</div><div class="v' + o + '">' + r.v(A) + '</div><div class="v rc' + o + '">' + r.v(B) + '</div>'; });
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(T("cmpH", { a: A.name, b: B.name })) + '</span></div>' +
      '<div class="cmpt in">' + html + '</div><p class="delta in">' + esc(T("delta", { p: money(Math.abs(B.month - A.month)) })) + '</p></div>';
  }
  function toPos(v, mn, mx) { return Math.round(1000 * Math.log(v / mn) / Math.log(mx / mn)); }
  function fromPos(p, mn, mx) { var v = mn * Math.pow(mx / mn, p / 1000); var mag = Math.pow(10, Math.max(0, Math.floor(Math.log10(v)) - 1)); return Math.max(mn, Math.round(v / mag) * mag); }
  function sceneRoi(a) {
    var k = calcCfg(); if (!k) return sceneWelcome();
    var p = plan(a.plan) || plans()[0], vars = calcVars(p);
    function ctl(inp) {
      var v = vars[inp.id], mn = +inp.min || 0, mx = +inp.max || 100, log = inp.scale === "log" && mn > 0;
      var pos = log ? toPos(Math.max(mn, Math.min(mx, v)), mn, mx) : Math.max(mn, Math.min(mx, v));
      return '<div class="ctl"><div class="row"><span>' + esc(inp.label) + '</span><b data-v="' + esc(inp.id) + '">' + esc(fmtOut(v, inp.format)) + '</b></div>' +
        '<input type="range" data-in="' + esc(inp.id) + '" min="' + (log ? 0 : mn) + '" max="' + (log ? 1000 : mx) + '" value="' + pos + '" aria-label="' + esc(inp.label) + '"></div>';
    }
    return '<div class="scene" data-plan="' + esc(p ? p.id : "") + '"><div class="head in"><span class="tag">' + esc(TX("calculator_title", T("roiH"))) + '</span></div>' +
      '<div class="roi"><div class="card in" style="gap:1.1em">' + (k.inputs || []).map(ctl).join("") + '</div>' +
      '<div class="out in"' + (p ? ' data-morph="plan-' + esc(p.id) + '"' : '') + ' id="r-out"></div></div></div>';
  }
  var roiTimer = 0;
  function paintRoi(ev) {
    var k = calcCfg(), sc = root.querySelector("[data-plan]"); if (!k || !sc) return;
    var p = plan(sc.getAttribute("data-plan")) || plans()[0], t = ev && ev.target;
    st.roi = st.roi || {};
    if (t && t.getAttribute("data-in")) {
      var inp = (k.inputs || []).filter(function (x) { return x.id === t.getAttribute("data-in"); })[0];
      if (inp) { var mn = +inp.min || 0, mx = +inp.max || 100; st.roi[inp.id] = inp.scale === "log" && mn > 0 ? fromPos(+t.value, mn, mx) : +t.value; }
    }
    var vars = calcVars(p);
    (k.inputs || []).forEach(function (inp) { var b = sc.querySelector('[data-v="' + inp.id + '"]'); if (b) b.textContent = fmtOut(vars[inp.id], inp.format); });
    var outs = k.outputs || [], big = outs.filter(function (o) { return o.big; })[0] || outs[0];
    if (!big) return;
    $("r-out").innerHTML = '<div class="big"><span>' + esc(big.label) + '</span><b>' + esc(fmtOut(calc(big.expr, vars), big.format)) + '</b></div><div class="rows">' +
      outs.filter(function (o) { return o !== big; }).map(function (o) {
        var lab = o.id === "plan_cost" && p ? o.label + " · " + p.name : o.label;
        return '<div class="r"><span>' + esc(lab) + '</span><b>' + esc(fmtOut(calc(o.expr, vars), o.format)) + '</b></div>'; }).join("") + '</div>';
    if (t) { clearTimeout(roiTimer); roiTimer = setTimeout(function () { var d = {}; (k.inputs || []).forEach(function (x) { d[x.id] = vars[x.id]; }); fire("roi", d); }, 900); }
  }
  function sceneCase(a) {
    var cs = C().cases || [], c = cs.filter(function (k) { return k.id === a.id; })[0] || cs[0];
    if (!c) return sceneWelcome();
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(TX("case_title", T("caseH"))) + '</span><h2 class="h">' + esc(c.industry) + '</h2></div>' +
      '<div class="card in" style="padding:1.6em 1.4em"><div class="case">' +
      '<div class="before"><div class="num">' + esc(c.before + c.unit) + '</div><div class="cap">' + esc(c.metric) + '</div></div><div class="arrow">→</div>' +
      '<div class="after"><div class="num" data-count="' + c.after + '" data-from="' + c.before + '" data-unit="' + esc(c.unit) + '">' + esc(c.after + c.unit) + '</div><div class="cap">' + esc(c.period) + '</div></div></div></div>' +
      (c.example ? '<p class="note in">' + esc(T("example")) + '</p>' : '') + '</div>';
  }
  function sceneClients() {
    var cl = C().clients || [];
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(TX("clients_title", T("clientsH"))) + '</span>' + (C().clients_note ? '<p class="sub">' + esc(C().clients_note) + '</p>' : '') + '</div>' +
      '<div class="logos">' + cl.map(function (c) { return '<div class="logo in" title="' + esc(c.name) + '">' + (c.logo ? '<img src="' + esc(url(c.logo)) + '" alt="' + esc(c.name) + '">' : esc(c.name)) + '</div>'; }).join("") + '</div></div>';
  }
  var ICONS = {
    check: '<path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8M8 13h5"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/>'
  };
  function sceneTrust() {
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(TX("trust_title", T("trustH"))) + '</span></div><div class="trust">' +
      (C().trust || []).map(function (t) { return '<div class="card in"><svg viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[t.icon] || ICONS.check) + '</svg><div><h3>' + esc(t.title) + '</h3><p>' + esc(t.text) + '</p></div></div>'; }).join("") + '</div></div>';
  }
  var SOCIAL = {
    telegram: '<path d="M21 4L3 11l6 2 2 6 3-4 5 4z"/><path d="M9 13l8-6"/>',
    instagram: '<rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.6"/><circle cx="17" cy="7" r=".6"/>',
    facebook: '<path d="M14 21v-8h3l.5-3.5H14V7.8c0-1 .4-1.8 1.8-1.8H18V3.2c-.5-.1-1.6-.2-2.8-.2-2.6 0-4.2 1.6-4.2 4.4v2.1H8V13h3v8"/>',
    tiktok: '<path d="M14 3v11.5a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 3c.5 2.6 2.2 4.2 5 4.5"/>'
  };
  function sceneContacts() {
    var K = C().contacts || {};
    function row(label, val, href, act, cls) { return '<div class="crow in"><div><span>' + esc(label) + '</span><b>' + esc(val) + '</b></div><a class="act ' + cls + '" href="' + esc(href) + '">' + esc(act) + '</a></div>'; }
    return '<div class="scene"><div class="head in"><span class="tag">' + esc(TX("contacts_title", T("contH"))) + '</span></div><div class="cgrid"><div class="contacts">' +
      (K.phones || []).map(function (p) { return row(p.label, p.value, "tel:" + String(p.value).replace(/[^\d+]/g, ""), T("call"), "call"); }).join("") +
      (K.email ? row("Email", K.email, "mailto:" + K.email, T("write"), "mail") : "") + '</div>' +
      '<div class="card in">' + (K.address ? '<p class="addr">' + esc(K.address) + '</p>' : '') +
      ((K.social || []).length ? '<span class="k2">' + esc(T("follow")) + '</span><div class="soc">' + K.social.map(function (x) {
        return '<a href="' + esc(x.url) + '" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" aria-hidden="true">' + (SOCIAL[String(x.name).toLowerCase()] || "") + '</svg>' + esc(x.name) + '</a>'; }).join("") + '</div>' : '') +
      '</div></div></div>';
  }
  function fmtPhone(p) { var d = String(p || "").replace(/\D/g, ""); if (/^373\d{8}$/.test(d)) return "+373 " + d.slice(3, 5) + " " + d.slice(5, 8) + " " + d.slice(8); return p ? (String(p).charAt(0) === "+" ? p : "+" + d) : ""; }
  function fmtSlot(s) {
    if (!s) return "";
    var d = new Date(String(s).replace(" ", "T")); if (isNaN(d)) return String(s);
    try { return d.toLocaleString(loc(), { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }); } catch (e) { return String(s); }
  }
  function sceneBooking(a) {
    function row(k, v, extra) { return v ? '<div class="brow in"><span>' + esc(T(k)) + '</span><b>' + esc(v) + (extra || "") + '</b></div>' : ""; }
    return '<div class="scene"><div class="book"><div class="head in"><span class="tag">' + esc(T("bookH")) + '</span><p class="sub">' + esc(T("bookSub")) + '</p></div>' +
      row("name", a.client_name) + row("phone", fmtPhone(a.phone), a.phone ? ' <span class="ok">✓ ' + esc(T("verified")) + '</span>' : '') +
      row("time", fmtSlot(a.start_time)) + row("task", a.request_summary) +
      '<button class="primary in" id="b-ok" type="button"' + (a.start_time ? '' : ' disabled') + '>' + esc(T("confirm")) + '</button></div></div>';
  }
  var SCENES = { welcome: sceneWelcome, services: sceneServices, plans: scenePlans, compare: sceneCompare, calculator: sceneRoi, roi: sceneRoi, "case": sceneCase, clients: sceneClients, trust: sceneTrust, contacts: sceneContacts, booking: sceneBooking };

  /* ----- engine: old scene leaves, new one types in; a card on both screens flies to its new place ----- */
  function show(name, args) {
    if (!SCENES[name] || !root) return;
    args = args || {};
    var panel = $("panel"), same = name === st.scene, seq = ++showSeq, reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel.querySelectorAll(".scene.leaving").forEach(function (el) { el.remove(); });
    var old = panel.querySelector(".scene");
    st.scene = name; st.args = args;
    var first = {};
    if (old) old.querySelectorAll("[data-morph]").forEach(function (el) { first[el.getAttribute("data-morph")] = el.getBoundingClientRect(); });
    if (!old || same || reduce) { if (old) old.remove(); mount(); return; }
    old.classList.add("leaving");
    setTimeout(function () { if (seq !== showSeq) return; old.remove(); mount(); }, 260);
    function mount() {
      var tmp = document.createElement("div"); tmp.innerHTML = SCENES[name](args); var sc = tmp.firstElementChild;
      sc.classList.add(same ? "soft" : "enter");
      var i = 0; sc.querySelectorAll(".in").forEach(function (el) { el.style.setProperty("--i", i++); });
      panel.appendChild(sc);
      bind(sc);
      if (same || reduce) return;
      sc.querySelectorAll("[data-morph]").forEach(function (el) {
        var f = first[el.getAttribute("data-morph")]; if (!f || !el.animate) return;
        var l = el.getBoundingClientRect(); if (!l.width || !l.height) return;
        el.classList.add("morphing");
        el.animate([{ transformOrigin: "top left", transform: "translate(" + (f.left - l.left) + "px," + (f.top - l.top) + "px) scale(" + (f.width / l.width) + "," + (f.height / l.height) + ")" },
                    { transformOrigin: "top left", transform: "none" }], { duration: 650, easing: "cubic-bezier(.2,.8,.2,1)" });
      });
      typeIn(sc);
    }
  }
  /* text types letter by letter; the newest letters glow in the brand colour; letters keep their place, nothing jumps */
  function typeIn(sc) {
    sc.querySelectorAll(".in").forEach(function (block) {
      if (block.classList.contains("morphing") || block.closest(".morphing")) return;
      var nodes = [], total = 0;
      var wk = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, { acceptNode: function (n) {
        return n.nodeValue.trim() && !n.parentNode.closest("svg, script, .morphing, [data-count]") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; } });
      while (wk.nextNode()) { nodes.push(wk.currentNode); total += wk.currentNode.nodeValue.replace(/\s/g, "").length; }
      if (!total) return;
      var t0 = (+block.style.getPropertyValue("--i") || 0) * 110 + 180, step = Math.max(7, Math.min(24, 1100 / total)), k = 0;
      nodes.forEach(function (n) {
        var f = document.createDocumentFragment();
        n.nodeValue.split(/(\s+)/).forEach(function (w) {
          if (!w) return;
          if (/^\s+$/.test(w)) { f.appendChild(document.createTextNode(w)); return; }
          var wd = document.createElement("span"); wd.className = "wd";
          for (var c = 0; c < w.length; c++) { var ch = document.createElement("span"); ch.className = "c"; ch.textContent = w[c]; ch.style.setProperty("--d", Math.round(t0 + k * step) + "ms"); k++; wd.appendChild(ch); }
          f.appendChild(wd);
        });
        n.parentNode.replaceChild(f, n);
      });
    });
  }
  function bind(sc) {
    sc.querySelectorAll("[data-bill]").forEach(function (b) { b.addEventListener("click", function () { st.billing = b.getAttribute("data-bill"); show(st.scene, st.args); fire("billing", { billing: st.billing }); }); });
    if (sc.querySelector("#r-out")) { sc.querySelectorAll("[data-in]").forEach(function (el) { el.addEventListener("input", paintRoi); }); paintRoi(); }
    sc.querySelectorAll("a.call").forEach(function (a) { a.addEventListener("click", function () { fire("call", { phone: a.getAttribute("href") }); }); });
    var ok = sc.querySelector("#b-ok");
    if (ok) ok.addEventListener("click", function () { ok.disabled = true; ok.textContent = "✓ " + T("confirmed"); fire("booking", st.args); });
    sc.querySelectorAll("[data-count]").forEach(function (el) {
      var from = +el.getAttribute("data-from"), to = +el.getAttribute("data-count"), unit = el.getAttribute("data-unit"), t0 = performance.now() + 400;
      (function step(t) { var k = Math.max(0, Math.min(1, (t - t0) / 1400)), e = 1 - Math.pow(1 - k, 3); el.textContent = Math.round(from + (to - from) * e) + unit; if (k < 1) requestAnimationFrame(step); })(t0);
    });
  }
  function fire(type, data) { var fn = cfg.on && cfg.on[type]; if (fn) { try { fn(data || {}); } catch (e) {} } }

  /* ----- dossier, voice line ----- */
  function renderDossier() {
    var p = st.profile || {}, out = [];
    ["activity", "problem", "volume"].forEach(function (k) { if (p[k]) out.push([T(k), p[k]]); });
    var sp = p.solution_plan && plan(p.solution_plan);
    if (sp) out.push([T("solution"), sp.name + " · " + money(sp.month) + " " + T("perMonth")]);
    $("dossier").innerHTML = out.map(function (x) { return '<div class="dz"><span>' + esc(x[0]) + '</span><b>' + esc(x[1]) + '</b></div>'; }).join("");
  }
  function caption(who, text, append) {
    var c = $("caption"); if (!c || !text) return;
    var label = who === "you" ? T("you") : (st.agent || T("agent"));
    if (append && c.getAttribute("data-who") === who) { var s = c.querySelector(".t"); s.textContent = (s.textContent + " " + text).replace(/\s+/g, " ").slice(-240); return; }
    c.setAttribute("data-who", who); c.className = "caption" + (who === "you" ? " you" : "");
    c.innerHTML = "<b>" + esc(label) + "</b><span class=\"t\">" + esc(text) + "</span>";
  }
  function orb(state, label) {
    if (st.orb) st.orb.set(state || "breathing");
    var v = $("vstate"); if (v) v.textContent = label || "";
  }

  /* ----- layer ----- */
  function ensure() {
    if (host) return;
    var b = C().brand || {};
    if (b.fonts_url && !document.getElementById("lu-scene-fonts")) {
      var l = document.createElement("link"); l.id = "lu-scene-fonts"; l.rel = "stylesheet"; l.href = b.fonts_url; document.head.appendChild(l);
    }
    host = document.createElement("div"); host.id = "lu-scenes";
    host.style.cssText = "position:fixed;inset:0;z-index:99991;display:none;";
    root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
    var vars = ":host{" +
      (b.ink ? "--ink:" + b.ink + ";" : "") + (b.paper ? "--paper:" + b.paper + ";" : "") + (b.muted ? "--muted:" + b.muted + ";" : "") +
      (b.accent ? "--accent:" + b.accent + ";" : "") + (b.card ? "--card:" + b.card + ";" : "") + (b.ok ? "--ok:" + b.ok + ";" : "") +
      (b.font_display ? "--font-d:" + b.font_display + ";" : "") + (b.font_body ? "--font-b:" + b.font_body + ";" : "") + "}";
    var bgP = b.bg_portrait ? 'url("' + url(b.bg_portrait) + '") center/cover, ' + (b.bg_fallback || "#ddd") : (b.bg_fallback || "#ddd");
    var bgL = b.bg_landscape ? 'url("' + url(b.bg_landscape) + '") center/cover, ' + (b.bg_fallback || "#ddd") : (b.bg_fallback || "#ddd");
    root.innerHTML = "<style>" + CSS + vars + ".ws{background:" + bgP + "}@media (orientation: landscape){.ws{background:" + bgL + "}}</style>" +
      '<div class="ws" id="ws" role="dialog" aria-modal="true">' +
      '<header class="top col"><div class="brand" id="brand"></div><button class="escape" id="escape" type="button"></button></header>' +
      '<div class="dossier col" id="dossier" aria-live="polite"></div>' +
      '<section class="panel col" id="panel" aria-live="polite"></section>' +
      '<div class="voice col"><canvas id="orb" aria-hidden="true"></canvas><div class="vtext"><div class="vstate" id="vstate"></div><div class="caption" id="caption"></div></div></div></div>';
    document.body.appendChild(host);
    $("brand").innerHTML = (b.logo ? '<img src="' + esc(url(b.logo)) + '" alt="">' : '') + '<span>' + esc(b.name || "") + '</span>';
    $("escape").textContent = T("escape");
    $("escape").addEventListener("click", function () { fire("escape"); });
    if (window.LuOrb) st.orb = window.LuOrb($("orb"), { state: "breathing", display: 60 });
  }
  function open() {
    ensure();
    if (st.open) return;
    st.open = true; host.style.display = "block";
    st.prevOverflow = document.documentElement.style.overflow; document.documentElement.style.overflow = "hidden";
  }
  function close() {
    if (!host || !st.open) return;
    st.open = false; host.style.display = "none"; document.documentElement.style.overflow = st.prevOverflow || "";
  }

  window.LuScenes = {
    configure: function (o) {
      o = o || {};
      if (o.catalog) cfg.catalog = o.catalog;
      if (o.lang) cfg.lang = UI[o.lang] ? o.lang : "en";
      if (o.base != null) cfg.base = String(o.base).replace(/\/$/, "");
      if (o.on) cfg.on = o.on;
    },
    ready: function () { return !!(cfg.catalog && (plans().length || (cfg.catalog.services || []).length)); },
    show: function (p) {
      if (!this.ready()) return false;
      p = p || {};
      open();
      if (p.agent) st.agent = p.agent;
      if (p.profile) { st.profile = p.profile; renderDossier(); }
      var a = p.args || {};
      if (a.billing === "year" || a.billing === "month") st.billing = a.billing;
      if (a.calc && typeof a.calc === "object") st.roi = Object.assign({}, st.roi || {}, a.calc);
      if ((p.scene === "calculator" || p.scene === "roi") && !st.roi) st.roi = {};
      show(p.scene, a);
      return true;
    },
    caption: function (who, text, append) { if (root) caption(who, text, append); },
    orb: function (state, label) { if (root) orb(state, label); },
    voice: function (speaking) { if (root) orb(speaking ? "listening" : "breathing", speaking ? (st.agent || T("agent")) : T("listening")); },
    ended: function () { if (root && st.open) orb("breathing", T("ended")); },
    close: close,
    isOpen: function () { return st.open; },
    scene: function () { return st.scene; }
  };

})();
