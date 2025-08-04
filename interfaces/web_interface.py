from flask import render_template_string

def html_index():
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>MEI Robô | IA de Áudio</title>
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
        <h1>🎤 Fale com a IA do MEI Robô</h1>
        <button id="recordBtn">🎙️ Gravar (5s)</button>
        <p id="status">Aguardando sua voz…</p>
        <audio id="audioPlayer" controls style="display:none; margin-top: 20px;"></audio>

        <script>
            const recordBtn = document.getElementById("recordBtn");
            const audioPlayer = document.getElementById("audioPlayer");
            const statusPara = document.getElementById("status");

            recordBtn.onclick = async () => {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    const mediaRecorder = new MediaRecorder(stream);
                    const audioChunks = [];

                    statusPara.textContent = "🎙️ Gravando…";

                    mediaRecorder.ondataavailable = (event) => {
                        if (event.data.size > 0) {
                            audioChunks.push(event.data);
                        }
                    };

                    mediaRecorder.onstop = async () => {
                        statusPara.textContent = "⏳ Enviando para IA…";

                        const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                        const formData = new FormData();
                        formData.append("audio", audioBlob, "audio.webm");

                        try {
                            const response = await fetch("/audio", {
                                method: "POST",
                                body: formData,
                            });

                            if (!response.ok) {
                                const error = await response.json();
                                console.error("❌ Erro na resposta da IA:", error);
                                statusPara.textContent = "❌ Erro: " + error.error;
                                return;
                            }

                            const blob = await response.blob();
                            audioPlayer.src = URL.createObjectURL(blob);
                            audioPlayer.style.display = "block";
                            audioPlayer.play();
                            statusPara.textContent = "✅ Resposta recebida!";
                        } catch (err) {
                            console.error("❌ Erro na requisição:", err);
                            statusPara.textContent = "❌ Erro ao enviar.";
                        }
                    };

                    mediaRecorder.start();

                    setTimeout(() => {
                        mediaRecorder.stop();
                        statusPara.textContent = "🛑 Gravação encerrada.";
                    }, 5000);
                } catch (err) {
                    console.error("Erro ao acessar microfone:", err);
                    alert("Permita o acesso ao microfone.");
                }
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content)
