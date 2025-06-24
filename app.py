import os
import re
import subprocess
from flask import Flask, render_template, request, redirect, url_for
from pathlib import Path

app = Flask(__name__)

class YouTubeToPDF:
    def __init__(self, output_path=None):
        self.output_path = output_path or os.getcwd()
        Path(self.output_path).mkdir(parents=True, exist_ok=True)

    def download_video(self, url, filename, max_retries=3):
        ydl_opts = {
            'outtmpl': filename,
            'format': 'best',
            'progress_hooks': [self.download_progress_hook]
        }
        retries = 0
        while retries < max_retries:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                return filename
            except yt_dlp.utils.DownloadError as e:
                print(f"Error downloading video: {e}. Retrying... ({retries + 1}/{max_retries})")
                retries += 1
        raise Exception("Failed to download video after multiple attempts.")

    def download_progress_hook(self, d):
        if d['status'] == 'downloading':
            try:
                progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                print(f"Download Progress: {progress:.1f}%", end='\r')
            except:
                print(f"Download Progress: {d['downloaded_bytes']} bytes", end='\r')
        elif d['status'] == 'finished':
            print("\nDownload completed. Processing video...")

    def get_video_id(self, url):
        patterns = [
            r"shorts\/(\w+)",
            r"youtu\.be\/([\w\-_]+)(\?.*)?",
            r"v=([\w\-_]+)",
            r"live\/(\w+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_playlist_videos(self, playlist_url):
        ydl_opts = {
            'ignoreerrors': True,
            'playlistend': 1000,
            'extract_flat': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist_info = ydl.extract_info(playlist_url, download=False)
            return [entry['url'] for entry in playlist_info['entries']]

    def extract_unique_frames(self, video_file, output_folder, n=3, ssim_threshold=0.8):
        print("Extracting frames...")
        cap = cv2.VideoCapture(video_file)
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        last_frame = None
        saved_frame = None
        frame_number = 0
        last_saved_frame_number = -1
        timestamps = []
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_number % n == 0:
                print(f"Processing frame: {frame_number}/{total_frames}", end='\r')
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray_frame = cv2.resize(gray_frame, (128, 72))

                if last_frame is not None:
                    similarity = ssim(gray_frame, last_frame, data_range=gray_frame.max() - gray_frame.min())

                    if similarity < ssim_threshold:
                        if saved_frame is not None and frame_number - last_saved_frame_number > fps:
                            frame_path = os.path.join(output_folder, f'frame{frame_number:04d}_{frame_number // fps}.png')
                            cv2.imwrite(frame_path, saved_frame)
                            timestamps.append((frame_number, frame_number // fps))

                        saved_frame = frame
                        last_saved_frame_number = frame_number
                    else:
                        saved_frame = frame
                else:
                    frame_path = os.path.join(output_folder, f'frame{frame_number:04d}_{frame_number // fps}.png')
                    cv2.imwrite(frame_path, frame)
                    timestamps.append((frame_number, frame_number // fps))
                    last_saved_frame_number = frame_number

                last_frame = gray_frame

            frame_number += 1

        cap.release()
        print("\nFrame extraction completed.")
        return timestamps

    def convert_frames_to_pdf(self, input_folder, output_file, timestamps, quality='medium'):
        print("Creating PDF...")
        pdf_quality = {'low': 72, 'medium': 150, 'high': 300}
        dpi = pdf_quality.get(quality, 150)
        
        frame_files = sorted(os.listdir(input_folder), key=lambda x: int(x.split('_')[0].split('frame')[-1]))
        pdf = FPDF("L")
        pdf.set_auto_page_break(0)

        for i, (frame_file, (frame_number, timestamp_seconds)) in enumerate(zip(frame_files, timestamps)):
            print(f"Adding page {i+1}/{len(frame_files)}", end='\r')
            frame_path = os.path.join(input_folder, frame_file)
            image = Image.open(frame_path)
            pdf.add_page()

            pdf.image(frame_path, x=0, y=0, w=pdf.w, h=pdf.h)

            timestamp = f"{timestamp_seconds // 3600:02d}:{(timestamp_seconds % 3600) // 60:02d}:{timestamp_seconds % 60:02d}"
            
            x, y, width, height = 5, 5, 60, 15
            region = image.crop((x, y, x + width, y + height)).convert("L")
            mean_pixel_value = region.resize((1, 1)).getpixel((0, 0))
            
            pdf.set_text_color(255, 255, 255) if mean_pixel_value < 64 else pdf.set_text_color(0, 0, 0)
            pdf.set_xy(x, y)
            pdf.set_font("Arial", size=12)
            pdf.cell(0, 0, timestamp)

        print("\nSaving PDF...")
        pdf.output(output_file)
        print("PDF creation completed.")

    def get_video_title(self, url):
        ydl_opts = {
            'skip_download': True,
            'ignoreerrors': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
            title = video_info['title']
            title = re.sub(r'[<>:"/\\|?*]', '-', title).strip('.')
            return title

    def process_url(self, url, quality='medium'):
        video_id = self.get_video_id(url)
        if video_id:
            self.process_single_video(url, quality)
        else:
            self.process_playlist(url, quality)

    def process_single_video(self, url, quality):
        temp_video = os.path.join(self.output_path, "temp_video.mp4")
        try:
            video_file = self.download_video(url, temp_video)
            if video_file:
                video_title = self.get_video_title(url)
                output_pdf = os.path.join(self.output_path, f"{video_title}.pdf")
                
                with tempfile.TemporaryDirectory() as temp_folder:
                    timestamps = self.extract_unique_frames(video_file, temp_folder)
                    self.convert_frames_to_pdf(temp_folder, output_pdf, timestamps, quality)
                
                print(f"PDF saved at: {output_pdf}")
        finally:
            if os.path.exists(temp_video):
                os.remove(temp_video)

    def process_playlist(self, url, quality):
        print("Processing playlist...")
        video_urls = self.get_playlist_videos(url)
        for i, video_url in enumerate(video_urls, 1):
            print(f"\nProcessing video {i}/{len(video_urls)}")
            self.process_single_video(video_url, quality)

@app.route('/process', methods=['POST'])
def process():
    video_type = request.form['video_type']
    quality = request.form['quality']
    url = request.form['url']
    output_path = request.form['output_path']

    # Validate URL
    if not validate_url(url):
        return "Invalid URL. Please go back and enter a valid YouTube URL."

    # Create an instance of YouTubeToPDF
    converter = YouTubeToPDF(output_path)
    
    # Process the URL
    try:
        converter.process_url(url, quality)
        return redirect(url_for('thank_you'))
    except Exception as e:
        return f"An error occurred: {str(e)}"

def validate_url(url):
    patterns = [
        r"shorts\/(\w+)",
        r"youtu\.be\/([\w\-_]+)(\?.*)?",
        r"v=([\w\-_]+)",
        r"live\/(\w+)"
    ]
    return any(re.search(pattern, url) for pattern in patterns)

if __name__ == '__main__':
    app.run(debug=True)
