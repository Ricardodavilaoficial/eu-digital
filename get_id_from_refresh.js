var f=new ActiveXObject("Scripting.FileSystemObject");
var t=f.OpenTextFile("token_refresh.json",1), s=t.ReadAll(); t.Close();
var m=/"id_token"\s*:\s*"([^"]+)"/.exec(s);
if(m){WScript.Echo(m[1]);}else{WScript.Quit(1);}
