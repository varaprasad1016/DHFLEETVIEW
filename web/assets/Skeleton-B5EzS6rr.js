import{w as C,x as w,e as b,y as k,k as S,C as x,E as R,F as M,G as $,aq as h,ar as m,as as c}from"./index-Bh9QGtkt.js";function U(t){return String(t).match(/[\d.\-+]*\s*(.*)/)[1]||""}function A(t){return parseFloat(t)}function X(t){return C("MuiSkeleton",t)}w("MuiSkeleton",["root","text","rectangular","rounded","circular","pulse","wave","withChildren","fitContent","heightAuto"]);const E=t=>{const{classes:e,variant:a,animation:o,hasChildren:s,width:n,height:i}=t;return R({root:["root",a,o,s&&"withChildren",s&&!n&&"fitContent",s&&!i&&"heightAuto"]},X,e)},r=h`
  0% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }

  100% {
    opacity: 1;
  }
`,l=h`
  0% {
    transform: translateX(-100%);
  }

  50% {
    /* +0.5s of delay between each loop */
    transform: translateX(100%);
  }

  100% {
    transform: translateX(100%);
  }
`,W=typeof r!="string"?m`
        animation: ${r} 2s ease-in-out 0.5s infinite;
      `:null,j=typeof l!="string"?m`
        &::after {
          animation: ${l} 2s linear 0.5s infinite;
        }
      `:null,B=M("span",{name:"MuiSkeleton",slot:"Root",overridesResolver:(t,e)=>{const{ownerState:a}=t;return[e.root,e[a.variant],a.animation!==!1&&e[a.animation],a.hasChildren&&e.withChildren,a.hasChildren&&!a.width&&e.fitContent,a.hasChildren&&!a.height&&e.heightAuto]}})($(({theme:t})=>{const e=U(t.shape.borderRadius)||"px",a=A(t.shape.borderRadius),o=c(t,{animation:"none"}),s=c(t,{"&::after":{animation:"none",display:"none"}});return{display:"block",backgroundColor:t.vars?t.vars.palette.Skeleton.bg:t.alpha(t.palette.text.primary,t.palette.mode==="light"?.11:.13),height:"1.2em",variants:[{props:{variant:"text"},style:{marginTop:0,marginBottom:0,height:"auto",transformOrigin:"0 55%",transform:"scale(1, 0.60)",borderRadius:`${a}${e}/${Math.round(a/.6*10)/10}${e}`,"&:empty:before":{content:'"\\00a0"'}}},{props:{variant:"circular"},style:{borderRadius:"50%"}},{props:{variant:"rounded"},style:{borderRadius:(t.vars||t).shape.borderRadius}},{props:({ownerState:n})=>n.hasChildren,style:{"& > *":{visibility:"hidden"}}},{props:({ownerState:n})=>n.hasChildren&&!n.width,style:{maxWidth:"fit-content"}},{props:({ownerState:n})=>n.hasChildren&&!n.height,style:{height:"auto"}},{props:{animation:"pulse"},style:W||{animation:`${r} 2s ease-in-out 0.5s infinite`}},...o?[{props:{animation:"pulse"},style:o}]:[],{props:{animation:"wave"},style:{position:"relative",overflow:"hidden",WebkitMaskImage:"-webkit-radial-gradient(white, black)","&::after":{background:`linear-gradient(
                90deg,
                transparent,
                ${(t.vars||t).palette.action.hover},
                transparent
              )`,content:'""',position:"absolute",transform:"translateX(-100%)",bottom:0,left:0,right:0,top:0}}},{props:{animation:"wave"},style:j||{"&::after":{animation:`${l} 2s linear 0.5s infinite`}}},...s?[{props:{animation:"wave"},style:s}]:[]]}})),K=b.forwardRef(function(e,a){const o=k({props:e,name:"MuiSkeleton"}),{animation:s="pulse",className:n,component:i="span",height:p,style:f,variant:g="text",width:y,...d}=o,u={...o,animation:s,component:i,variant:g,hasChildren:!!d.children},v=E(u);return S.jsx(B,{as:i,ref:a,className:x(v.root,n),ownerState:u,...d,style:{width:y,height:p,...f}})});export{K as S};
