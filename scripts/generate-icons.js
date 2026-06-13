const fs = require('fs');
const { createCanvas } = require('canvas');

const sizes = [16, 48, 128];

const drawIcon = (size) => {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext('2d');
  
  // Background (dark)
  ctx.fillStyle = '#020617';
  ctx.fillRect(0, 0, size, size);
  
  // Border (cyan)
  ctx.strokeStyle = '#06b6d4';
  ctx.lineWidth = size / 32;
  ctx.beginPath();
  ctx.arc(size/2, size/2, size/2 - size/16, 0, Math.PI * 2);
  ctx.stroke();
  
  // Inner hexagon/shield shape
  ctx.strokeStyle = '#06b6d4';
  ctx.lineWidth = size / 16;
  
  if (size >= 48) {
    // Draw a simple shield/hexagon shape
    const cx = size / 2;
    const cy = size / 2;
    const r = size / 3;
    
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const angle = (i * 60 - 30) * Math.PI / 180;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
    
    // Center dot
    ctx.fillStyle = '#06b6d4';
    ctx.beginPath();
    ctx.arc(cx, cy, size/12, 0, Math.PI * 2);
    ctx.fill();
  }
  
  return canvas.toBuffer('image/png');
};

sizes.forEach(size => {
  const buffer = drawIcon(size);
  fs.writeFileSync(`public/icons/icon${size}.png`, buffer);
  console.log(`Generated icon${size}.png`);
});

console.log('\nAll icons generated successfully!');
console.log('Note: If canvas module is not installed, run: npm install --save-dev canvas');
