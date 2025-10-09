var f=new ActiveXObject("Scripting.FileSystemObject");
var t=f.OpenTextFile("idtoken.json",1), s=t.ReadAll(); t.Close();
var m=/"idToken"\s*:\s*"([^"]+)"/.exec(s), r=/"refreshToken"\s*:\s*"(["]+)"/.exec(s);
if(m) WScript.Echo("IDTOKEN="+m[1]);
if(r) WScript.Echo("REFRESH_TOKEN="+r[1]);
