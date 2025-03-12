from cog import Input, Path
import moderngl
import numpy as np
from PIL import Image
import random
import re
import cv2
import subprocess
import os


def goo(
    seed: int = Input(
        default=-1,
        description="Seed for the random number generator",
    ),
    width: int = Input(
        default=512,
        description="Dimension of the output image",
        ge=1,
        le=4096,
    ),
    height: int = Input(
        default=512,
        description="Height of the output image",
        ge=1,
        le=4096,
    ),
    scale: int = 1,
    depth: int = 3,
    format: str = Input(
        description="Format of the output (image or video)",
        choices=["png", "jpeg", "tiff", "mp4"],
        default="png",
    ),
    speed: float = Input(
        default=2.0,
        description="Speed of the goo animation effect",
        ge=0.0,
        le=10.0,
    ),
    num_frames: int = Input(
        default=60 * 10,
        description="Number of frames for video output (only used when format is mp4)",
        ge=1,
        le=600,
    ),
    fps: int = Input(
        default=60,
        description="Frames per second for video output (only used when format is mp4)",
        ge=1,
        le=60,
    ),
) -> Path:
    if seed == -1:
        seed = int(random.random() * 2**16)

    ctx = moderngl.create_context(
        standalone=True,
        backend="egl",
    )

    prog = ctx.program(
        vertex_shader="""
        #version 330
        in vec2 position;
        void main() {
            gl_Position = vec4(position, 0.0, 1.0);
        }
        """,
        fragment_shader=f"""
        #version 330
        precision mediump float;
        uniform vec2 iResolution;
        uniform float iTime;
        uniform vec2 iMouse;

        vec3 color1 = vec3(235.0/255.0, 231.0/255.0, 92.0/255.0);
        vec3 color2 = vec3(223.0/255.0, 72.0/255.0, 67.0/255.0);
        vec3 color3 = vec3(235.0/255.0, 64.0/255.0, 240.0/255.0);

        vec2 effect(vec2 p, float i, float time) {{
            vec2 mouse = vec2(0.0, 0.0); // Ignoring mouse input as per instructions
            return vec2(sin(p.x * i + time) * cos(p.y * i + time), sin(length(p.x)) * cos(length(p.y)));
        }}

        void main() {{
            vec2 p = (2.0 * gl_FragCoord.xy - iResolution.xy) / max(iResolution.x, iResolution.y);
            p.x += {seed:.1f}; // Use the seed prop to offset the starting position of the goo effect
            p.y += {seed:.1f};

            p *= {scale:.1f};
            for (int i = 1; i < {depth}; i++) {{
                float fi = float(i);
                p += effect(p, fi, iTime * ({speed:.1f}/10));
            }}
            vec3 col = mix(mix(color1, color2, 1.0-sin(p.x)), color3, cos(p.y+p.x));
            gl_FragColor = vec4(col, 1.0);
        }}
    """,
    )

    vertices = np.array(
        [
            -1.0,
            -1.0,
            1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            1.0,
        ],
        dtype="f4",
    )

    vbo = ctx.buffer(vertices)
    vao = ctx.simple_vertex_array(prog, vbo, "position")
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((width, height), 4)])

    if format == "mp4":
        # Set up FFmpeg process for MP4/H.264 encoding
        filename = "/tmp/output.mp4"
        ffmpeg_cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file if it exists
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}',
            '-pix_fmt', 'rgb24',
            '-r', str(fps),
            '-i', '-',  # Read from stdin
            '-c:v', 'libx264',  # Use H.264 codec
            '-preset', 'fast',  # Encoding preset
            '-profile:v', 'baseline',  # Most compatible H.264 profile
            '-pix_fmt', 'yuv420p',  # Required for browser compatibility
            '-movflags', '+faststart',  # Enable streaming
            '-crf', '23',  # Quality setting (lower = better, 23 is a good default)
            filename
        ]
        
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        try:
            # Generate frames
            for frame in range(num_frames):
                fbo.use()
                ctx.clear()
                iResolution = (width, height)
                iTime = frame / fps
                prog["iResolution"].value = iResolution
                prog["iTime"].value = iTime
                vao.render(moderngl.TRIANGLES)

                data = fbo.read(components=3)
                image = Image.frombytes("RGB", fbo.size, data)
                image = image.transpose(Image.FLIP_TOP_BOTTOM)
                
                # Write raw frame data directly to FFmpeg's stdin
                ffmpeg_process.stdin.write(image.tobytes())
            
            # Close stdin and wait for FFmpeg to finish
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
            
            if ffmpeg_process.returncode != 0:
                raise RuntimeError(f"FFmpeg encoding failed with error: {ffmpeg_process.stderr.read().decode()}")
                
        finally:
            # Ensure resources are cleaned up
            if ffmpeg_process.poll() is None:
                ffmpeg_process.terminate()
                ffmpeg_process.wait()

        return Path(filename)
    else:
        # Original image generation code
        fbo.use()
        ctx.clear()
        iResolution = (width, height)
        iTime = 1  # Modulo to prevent too large numbers
        prog["iResolution"].value = iResolution
        prog["iTime"].value = iTime
        vao.render(moderngl.TRIANGLES)  # pylint: disable=no-member

        data = fbo.read(components=3)
        image = Image.frombytes("RGB", fbo.size, data)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)  # pylint: disable=no-member

        # Save the output image
        ext = re.sub(r"\W+", "", format)
        if format == "jpeg":
            image = image.convert("RGB")
            ext = "jpg"
        filename = f"/tmp/output.{ext}"
        image.save(filename, format=format)

        return Path(filename)
