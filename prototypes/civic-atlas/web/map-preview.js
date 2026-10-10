import * as THREE from '/viewer/vendor/three.module.js';

// Reuse the map's renderer and completed artwork. No additional WebGL context,
// on-screen camera movement, or mutation of the saved world is involved.
const caches = new WeakMap();
const LIMIT = 48;

export async function propertyPreview(map, home) {
  let cache = caches.get(map);
  if (!cache) { cache = new Map(); caches.set(map, cache); }
  if (cache.has(home.id)) return cache.get(home.id);
  const pending = (async () => {
    await map.visualReady;
    if (map.abort?.signal.aborted) throw new Error('Map is closed.');
    return captureProperty(map, home);
  })();
  cache.set(home.id, pending);
  try {
    const result = await pending;
    while (cache.size > LIMIT) cache.delete(cache.keys().next().value);
    return result;
  } catch (error) {
    cache.delete(home.id);
    throw error;
  }
}

function captureProperty(map, home) {
  const s = map.scene, renderer = s.renderer;
  if (!s.camera.isOrthographicCamera || renderer.getContext().isContextLost()) {
    throw new Error('Property preview is unavailable.');
  }
  const size = 256, camera = s.camera.clone();
  const target = new THREE.Vector3(home.x, s.heightAt(home.x, home.z) + (home.height || 5) * .45, home.z);
  const direction = s.camera.getWorldDirection(new THREE.Vector3());
  // Retain the exact map orientation: illustrated foliage/buildings are authored
  // for this viewing angle, and must not become a separate orbiting scene.
  camera.position.copy(target).addScaledVector(direction, -Math.max(s.span * 2, 400));
  camera.quaternion.copy(s.camera.quaternion);
  const inverseRotation = camera.quaternion.clone().invert();
  const halfW = Math.max(home.width || 12, 8) / 2;
  const halfD = Math.max(home.depth || 10, 8) / 2;
  const height = Math.max(home.height || 5, 3);
  const c = Math.cos(home.angle || 0), n = Math.sin(home.angle || 0);
  let extent = 0;
  for (const x of [-halfW, halfW]) for (const z of [-halfD, halfD]) for (const y of [-height * .45, height * .7]) {
    const point = new THREE.Vector3(x*c-z*n, y, x*n+z*c).applyQuaternion(inverseRotation);
    extent = Math.max(extent, Math.abs(point.x), Math.abs(point.y));
  }
  extent = Math.max(13, extent * 1.5);
  camera.left = camera.bottom = -extent;
  camera.right = camera.top = extent;
  camera.zoom = 1;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);

  const renderTarget = new THREE.WebGLRenderTarget(size, size, {
    format: THREE.RGBAFormat,
    type: THREE.HalfFloatType,
    colorSpace: THREE.LinearSRGBColorSpace,
    depthBuffer: true,
    stencilBuffer: false,
    samples: 4,
  });
  // Three renders ordinary targets in linear working space without the screen's
  // output transform. Preserve HDR highlights, then apply the same display pass.
  const outputTarget = new THREE.WebGLRenderTarget(size, size, {
    type: THREE.UnsignedByteType, colorSpace: THREE.LinearSRGBColorSpace,
    depthBuffer: false, stencilBuffer: false,
  });
  const toneFunction = {
    [THREE.LinearToneMapping]: 'LinearToneMapping',
    [THREE.ReinhardToneMapping]: 'ReinhardToneMapping',
    [THREE.CineonToneMapping]: 'CineonToneMapping',
    [THREE.ACESFilmicToneMapping]: 'ACESFilmicToneMapping',
    [THREE.AgXToneMapping]: 'AgXToneMapping',
    [THREE.NeutralToneMapping]: 'NeutralToneMapping',
  }[renderer.toneMapping];
  const outputMaterial = new THREE.RawShaderMaterial({
    uniforms: { tDiffuse: { value: renderTarget.texture }, toneMappingExposure: { value: renderer.toneMappingExposure } },
    vertexShader: `precision highp float;
      attribute vec3 position; attribute vec2 uv; varying vec2 vUv;
      void main(){vUv=uv;gl_Position=vec4(position,1.0);}`,
    fragmentShader: `precision highp float;
      uniform sampler2D tDiffuse; varying vec2 vUv;
      #include <tonemapping_pars_fragment>
      #include <colorspace_pars_fragment>
      void main(){
        gl_FragColor=texture2D(tDiffuse,vUv);
        ${toneFunction ? `gl_FragColor.rgb=${toneFunction}(gl_FragColor.rgb);` : ''}
        ${renderer.outputColorSpace === THREE.SRGBColorSpace ? 'gl_FragColor=sRGBTransferOETF(gl_FragColor);' : ''}
      }`,
    depthTest: false, depthWrite: false, blending: THREE.NoBlending,
  });
  const outputGeometry = new THREE.PlaneGeometry(2, 2);
  const outputScene = new THREE.Scene();
  outputScene.add(new THREE.Mesh(outputGeometry, outputMaterial));
  const outputCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const oldTarget = renderer.getRenderTarget();
  const oldFace = renderer.getActiveCubeFace();
  const oldMip = renderer.getActiveMipmapLevel();
  const viewport = renderer.getViewport(new THREE.Vector4());
  const scissor = renderer.getScissor(new THREE.Vector4());
  const scissorTest = renderer.getScissorTest();
  const pixels = new Uint8Array(size * size * 4);
  try {
    renderer.setRenderTarget(renderTarget);
    // setRenderTarget uses target pixel dimensions directly, independent of DPR.
    renderer.setScissorTest(false);
    renderer.render(s.scene, camera);
    renderer.setRenderTarget(outputTarget);
    renderer.render(outputScene, outputCamera);
    renderer.readRenderTargetPixels(outputTarget, 0, 0, size, size, pixels);
  } finally {
    renderer.setViewport(viewport);
    renderer.setScissor(scissor);
    renderer.setScissorTest(scissorTest);
    renderer.setRenderTarget(oldTarget, oldFace, oldMip);
    renderTarget.dispose();
    outputTarget.dispose();
    outputGeometry.dispose();
    outputMaterial.dispose();
  }
  const visible = pixels.some((value, index) => index % 4 === 3 && value !== 0);
  let varied = false;
  for (let i = 4; i < pixels.length && !varied; i += 4) {
    varied = Math.abs(pixels[i] - pixels[0]) + Math.abs(pixels[i + 1] - pixels[1]) + Math.abs(pixels[i + 2] - pixels[2]) > 8;
  }
  if (!visible || !varied) throw new Error('Property preview did not render.');
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Property preview is unavailable.');
  const frame = context.createImageData(size, size);
  // WebGL reads from the bottom-left; ImageData is ordered from the top-left.
  const stride = size * 4;
  for (let y = 0; y < size; y++) {
    frame.data.set(pixels.subarray((size - y - 1) * stride, (size - y) * stride), y * stride);
  }
  context.putImageData(frame, 0, 0);
  return canvas.toDataURL('image/png');
}
