from flask import render_template_string

def html_index():
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Eu Digital | Assistente de Voz</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                margin-top: 50px;
            }
            button {
                font-size: 1.2rem;
                padding: 10px 20px;
                cursor: pointer;
            }
            #status {
                margin: 15px 0;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <h1>🎙️ Fale algo e ouça a resposta da IA!</h1>
        <button id="startBtn">🎤 Gravar</button>
        <p id="status">Aguardando sua voz...</p>
        <audio id="responseAudio" controls style="margin-top: 20px;"></audio>

        <script>
            let mediaRecorder;
            let audioChunks = [];

            const startBtn = document.getElementById("startBtn");
            const statusPara = document.getElementById("status");
            const responseAudio = document.getElementById("responseAudio");

            startBtn.onclick = async () => {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    statusPara.textContent = "🎙️ Gravando…";

                    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);

                    mediaRecorder.onstop = async () => {
                        statusPara.textContent = "⏳ Enviando para IA…";

                        const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                        const formData = new FormData();
                        formData.append("file", audioBlob, "gravacao.webm");
                        formData.append("tipo", "audio");

                        try {
                            const response = await fetch("/audio", {
                                method: "POST",
                                body: formData,
                            });

                            if (!response.ok) {
                                console.error("❌ Erro na resposta da IA:", response.statusText);
                                alert("Erro ao processar o áudio.");
                                statusPara.textContent = "⚠️ Erro na resposta da IA.";
                                return;
                            }

                            const audioBuffer = await response.blob();
                            responseAudio.src = URL.createObjectURL(audioBuffer);
                            responseAudio.play();
                            statusPara.textContent = "✅ Resposta recebida!";
                        } catch (err) {
                            console.error("❌ Erro na requisição:", err);
                            alert("Erro ao enviar áudio.");
                            statusPara.textContent = "⚠️ Erro ao enviar.";
                        }
                    };

                    mediaRecorder.start();

                    setTimeout(() => {
                        mediaRecorder.stop();
                        statusPara.textContent = "🛑 Gravação encerrada.";
                    }, 3000);

                } catch (err) {
                    console.error("Erro ao acessar o microfone:", err);
                    alert("Erro ao acessar o microfone. Verifique as permissões.");
                }
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content)
