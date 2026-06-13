// load config with dirty synchronous call
url = window.location.origin + '/config';
var config;
var xhr = new XMLHttpRequest();
xhr.open("GET", url, false);
xhr.send();
if (xhr.status === 200) {
    config = JSON.parse(xhr.responseText);
} else {
    console.error('Request failed with status:', xhr.status);
}

// fix tile server URL prefix
for (var key in config['map']['tile_server']) {
  if (config['map']['tile_server'].hasOwnProperty(key)) {
      var value = config['map']['tile_server'][key];
      var prefix = is_localhost(value) ? 'http://' : 'https://';
      config['map']['tile_server'][key] = prefix + value;
  }
}

// default map view centre
var centerLatitude = config['map']['location']['latitude'];
var centerLongitude = config['map']['location']['longitude'];

// bounding box for initial map view
var metersPerDegreeLongitude = 111320 * Math.cos(centerLatitude * Math.PI / 180);
var metersPerDegreeLatitude = 111132.954 - 559.822 * Math.cos(
  2 * centerLatitude * Math.PI / 180) + 1.175 *
  Math.cos(4 * centerLatitude * Math.PI / 180);
var widthDegrees  = config['map']['center_width']  / metersPerDegreeLongitude;
var heightDegrees = config['map']['center_height'] / metersPerDegreeLatitude;
var west  = centerLongitude - widthDegrees  / 2;
var south = centerLatitude  - heightDegrees / 2;
var east  = centerLongitude + widthDegrees  / 2;
var north = centerLatitude  + heightDegrees / 2;

// tile URL templates for each named layer (standard XYZ/PNG format)
var tileUrls = {
  osm:         config['map']['tile_server']['osm']         + '{z}/{x}/{y}.png',
  carto_light: config['map']['tile_server']['carto_light'] + '{z}/{x}/{y}.png',
  carto_dark:  config['map']['tile_server']['carto_dark']  + '{z}/{x}/{y}.png',
  opentopomap: config['map']['tile_server']['opentopomap'] + '{z}/{x}/{y}.png',
};

var tileAttributions = {
  osm:         '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  carto_light: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, © <a href="https://carto.com/attributions">CARTO</a>',
  carto_dark:  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, © <a href="https://carto.com/attributions">CARTO</a>',
  opentopomap: '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
};

var currentTileLayer = 'osm';

// set to true once map.on('load') completes and all layers exist
var mapLoaded = false;

// global feature store – each entry is a GeoJSON Feature representing a plotted point
var pointFeatures = [];

// Altitude unit preference — persisted in localStorage.  'm' (metres) or 'ft' (feet).
// getAltitudeColor() ALWAYS receives metres internally; this only affects display labels
// and the legend bar text.
var altUnit = (function() {
  try { return localStorage.getItem('3lips_altUnit') || 'm'; } catch(e) { return 'm'; }
})();

/**
 * @brief Strips HTML/XML special characters from a string to prevent
 * injection when external data (e.g. flight callsigns) is used in
 * MapLibre text-field expressions.
 * @param {string} text - Raw input string.
 * @returns {string} Sanitized string.
 */
function sanitizeLabel(text) {
  if (typeof text !== 'string') return '';
  return text.replace(/[<>&"']/g, '');
}

/**
 * @brief Formats an altitude value (in metres) for display according to current altUnit.
 * @param {number} alt_m - Altitude in metres.
 * @returns {string} e.g. "10500m" or "34449ft"
 */
function formatAltitude(alt_m) {
  if (altUnit === 'ft') {
    return Math.round(alt_m * 3.28084) + 'ft';
  }
  return Math.round(alt_m) + 'm';
}

/**
 * @brief Rebuilds the legend bar labels with proportional positioning.
 * Label positions are set via CSS left: X% where X = altitude / 12000 * 100,
 * so the spacing accurately reflects the non-uniform altitude brackets.
 * Called on map load and whenever the altitude unit is toggled.
 */
function updateLegendLabels() {
  var labelsEl = document.getElementById('legend-labels');
  if (!labelsEl) return;
  var breakpoints_m = [0, 150, 300, 600, 1200, 1800, 2400, 3000, 6000, 9000, 12000];
  var html = '';
  for (var i = 0; i < breakpoints_m.length; i++) {
    var pct = (breakpoints_m[i] / 12000) * 100;
    var text;
    if (altUnit === 'ft') {
      text = Math.round(breakpoints_m[i] * 3.28084) + 'ft';
    } else {
      text = breakpoints_m[i] + 'm';
    }
    html += '<span style="left:' + pct.toFixed(2) + '%;">' + text + '</span>';
  }
  labelsEl.innerHTML = html;
}

/**
 * @brief Toggles altitude unit between metres and feet, updates labels and legend.
 */
function toggleAltitudeUnit() {
  altUnit = (altUnit === 'm') ? 'ft' : 'm';
  try { localStorage.setItem('3lips_altUnit', altUnit); } catch(e) {}
  updateLegendLabels();
  // Re-flush all label features to force text-field re-evaluation
  _rebuildAllLabels();
  // Update settings popup button text
  var btn = document.getElementById('btn-alt-unit');
  if (btn) btn.textContent = 'Unit: ' + (altUnit === 'm' ? 'metres' : 'feet');
  var popup = document.getElementById('settings-popup');
  if (popup) popup.style.display = 'none';
}

/**
 * @brief Toggles the settings popup visibility.
 */
function toggleSettingsPopup() {
  var popup = document.getElementById('settings-popup');
  if (!popup) return;
  popup.style.display = (popup.style.display === 'block') ? 'none' : 'block';
}

// global vars used by event handlers
var adsb_url;

var style_adsb = {};
style_adsb.color = 'rgba(255, 0, 0, 0.5)';
style_adsb.pointSize = 8;
style_adsb.type = "adsb";

// initialise MapLibre GL map with an empty base style; sources and layers are
// added after the map fires its 'load' event
var map = new maplibregl.Map({
  container: 'mapContainer',
  style: {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {},
    layers: [],
  },
  center: [centerLongitude, centerLatitude],
  zoom: 9,
});

/**
 * @brief Maps altitude in metres to a colour on the orange→yellow→green→blue→purple spectrum.
 * @param {number} alt_m - Altitude in metres above WGS-84 ellipsoid.
 * @returns {string} CSS hsla colour string (hsla(hue, 80%, 55%, alpha)).
 */
function getAltitudeColor(alt_m) {
  // Clamp to defined range; below 0 → orange, above 12000 → purple
  if (alt_m <= 0) return 'hsla(30, 80%, 55%, 0.85)';

  // Piecewise-linear hue interpolation across altitude brackets
  var stops = [
    { alt: 0,     hue: 30  },  // orange
    { alt: 150,   hue: 30  },  // orange
    { alt: 300,   hue: 35  },  // lighter orange
    { alt: 600,   hue: 42  },  // orange-yellow
    { alt: 1200,  hue: 55  },  // yellow
    { alt: 1800,  hue: 75  },  // yellow-green
    { alt: 2400,  hue: 95  },  // yellowish green
    { alt: 3000,  hue: 120 },  // green
    { alt: 6000,  hue: 195 },  // light blue
    { alt: 9000,  hue: 230 },  // blue
    { alt: 12000, hue: 280 },  // purple
  ];

  // Above max → clamp to purple
  if (alt_m >= 12000) return 'hsla(280, 80%, 55%, 0.85)';

  // Find bracket
  for (var i = 0; i < stops.length - 1; i++) {
    if (alt_m >= stops[i].alt && alt_m <= stops[i + 1].alt) {
      var t = (alt_m - stops[i].alt) / (stops[i + 1].alt - stops[i].alt);
      var hue = stops[i].hue + t * (stops[i + 1].hue - stops[i].hue);
      return 'hsla(' + hue.toFixed(1) + ', 80%, 55%, 0.85)';
    }
  }

  return 'hsla(280, 80%, 55%, 0.85)'; // fallback purple
}

// Global registry of target label features from both ADS-B and detection sources.
// Keyed by source+hex so each script can update its own entries independently.
var _targetLabelFeatures = {};

/**
 * @brief Registers or updates a label feature for a target.
 *
 * Each caller passes a unique `sourceKey` (e.g. "adsb" or "detection") so that
 * labels from different poll loops don't overwrite each other.
 *
 * @param {string} sourceKey  - Namespace key ("adsb" or "detection").
 * @param {string} hex        - ICAO hex or target identifier.
 * @param {number} lat        - Latitude in degrees.
 * @param {number} lon        - Longitude in degrees.
 * @param {string} label      - Display text (e.g. "BAW123 · 10500m").
 * @param {string} color      - CSS colour string matching the dot colour.
 */
function updateTargetLabel(sourceKey, hex, lat, lon, label, color) {
  var id = sourceKey + '_' + hex;
  _targetLabelFeatures[id] = {
    type: 'Feature',
    id: id,
    geometry: { type: 'Point', coordinates: [lon, lat] },
    properties: { label: label, color: color },
  };
  _flushTargetLabels();
}

/**
 * @brief Removes a label feature for a target.
 * @param {string} sourceKey - Namespace key.
 * @param {string} hex       - ICAO hex or target identifier.
 */
function removeTargetLabel(sourceKey, hex) {
  var id = sourceKey + '_' + hex;
  delete _targetLabelFeatures[id];
  _flushTargetLabels();
}

/**
 * @brief Removes all label features for a given source key.
 * @param {string} sourceKey - Namespace key to clear.
 */
function clearTargetLabels(sourceKey) {
  var prefix = sourceKey + '_';
  for (var id in _targetLabelFeatures) {
    if (_targetLabelFeatures.hasOwnProperty(id) && id.indexOf(prefix) === 0) {
      delete _targetLabelFeatures[id];
    }
  }
  _flushTargetLabels();
}

/**
 * @brief Pushes current label features to the map source.
 */
function _flushTargetLabels() {
  if (!mapLoaded) return;
  var source = map.getSource('target-labels');
  if (!source) return;
  var features = [];
  for (var id in _targetLabelFeatures) {
    if (_targetLabelFeatures.hasOwnProperty(id)) {
      features.push(_targetLabelFeatures[id]);
    }
  }
  source.setData({ type: 'FeatureCollection', features: features });
}

/**
 * @brief Rebuilds all label feature text without changing their positions.
 * Used after switching altitude units so labels reflect the new unit.
 */
function _rebuildAllLabels() {
  // ADS-B labels are rebuilt on the next event_adsb() poll.
  // Detection labels are rebuilt on the next event_radar() poll.
  // Just flush whatever we have now — the unit change will be picked up
  // when the poll loops re-generate their label text.
  _flushTargetLabels();
}

map.on('load', function () {

  mapLoaded = true;

  // fit the initial view to the configured area bounds
  map.fitBounds([[west, south], [east, north]], { animate: false });

  // add one raster source per tile provider; all but the default start hidden
  for (var layerName in tileUrls) {
    map.addSource('tiles-' + layerName, {
      type: 'raster',
      tiles: [tileUrls[layerName]],
      tileSize: 256,
      attribution: tileAttributions[layerName],
    });
    map.addLayer({
      id: 'layer-' + layerName,
      type: 'raster',
      source: 'tiles-' + layerName,
      layout: {
        visibility: layerName === currentTileLayer ? 'visible' : 'none',
      },
    });
  }

  // add GeoJSON source for all plotted points
  map.addSource('points', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });

  // circle layer rendered for every point type
  map.addLayer({
    id: 'points-circle',
    type: 'circle',
    source: 'points',
    paint: {
      'circle-color':   ['get', 'color'],
      'circle-radius':  ['/', ['to-number', ['get', 'size']], 2],
      'circle-opacity': ['get', 'opacity'],
    },
  });

  // text label layer rendered only for radar site points
  map.addLayer({
    id: 'points-label',
    type: 'symbol',
    source: 'points',
    filter: ['==', ['get', 'type'], 'radar'],
    layout: {
      'text-field':  ['get', 'name'],
      'text-font':   ['Open Sans Regular', 'Arial Unicode MS Regular'],
      'text-size':   14,
      'text-offset': [0, -1.5],
      'text-anchor': 'bottom',
    },
    paint: {
      'text-color':       '#000000',
      'text-halo-color':  '#ffffff',
      'text-halo-width':  2,
    },
  });

  // GeoJSON source for target call sign + altitude labels
  map.addSource('target-labels', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });

  // symbol layer for target labels (ADS-B and detection)
  // Uses a dark semi-transparent halo for a subtle background pill effect
  // and white text so it's readable against any map tile layer.
  map.addLayer({
    id: 'target-labels-text',
    type: 'symbol',
    source: 'target-labels',
    layout: {
      'text-field':  ['get', 'label'],
      'text-font':   ['Open Sans Regular', 'Arial Unicode MS Regular'],
      'text-size':   11,
      'text-offset': [0, -1.1],
      'text-anchor': 'bottom',
    },
    paint: {
      'text-color':        '#ffffff',
      'text-halo-color':   'rgba(0, 0, 0, 0.55)',
      'text-halo-width':   3.5,
    },
  });

  // add radar site points (rx and tx) from each blah2 server
  const radar_names = new URLSearchParams(
    window.location.search).getAll('server');
  var radar_config_urls = radar_names.map(
    name => window.location.origin + '/api/proxy/config?server=' + encodeURIComponent(name));
  var style_radar = {};
  style_radar.color = 'rgba(0, 0, 0, 1.0)';
  style_radar.pointSize = 10;
  style_radar.type = "radar";
  style_radar.timestamp = Date.now();
  radar_config_urls.forEach(url => {
    fetch(url)
      .then(response => {
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        return response.json();
      })
      .then(data => {
        // add radar rx and tx sites
        if (!doesEntityNameExist(data.location.rx.name)) {
          addPoint(
            data.location.rx.latitude,
            data.location.rx.longitude,
            data.location.rx.altitude,
            data.location.rx.name,
            style_radar.color,
            style_radar.pointSize,
            style_radar.type,
            style_radar.timestamp
          );
        }
        if (!doesEntityNameExist(data.location.tx.name)) {
          addPoint(
            data.location.tx.latitude,
            data.location.tx.longitude,
            data.location.tx.altitude,
            data.location.tx.name,
            style_radar.color,
            style_radar.pointSize,
            style_radar.type,
            style_radar.timestamp
          );
        }
      })
      .catch(error => {
        console.error('Error during fetch:', error);
      });
  });

  // resolve ADS-B truth URL through our proxy to avoid direct client-to-node requests
  var adsb_param = new URLSearchParams(window.location.search).get('adsb');
  if (adsb_param && adsb_param.trim() !== '') {
    adsb_url = window.location.origin + '/api/proxy/adsb?url=' + encodeURIComponent(adsb_param);
  } else {
    adsb_url = null;
  }

  // initialise settings button text (replaces inline <script> in HTML)
  var btnUnit = document.getElementById('btn-alt-unit');
  if (btnUnit) btnUnit.textContent = 'Unit: ' + (altUnit === 'm' ? 'metres' : 'feet');

  // replace static legend labels with proportionally-positioned ones
  updateLegendLabels();

  // start polling event loops
  if (adsb_url) {
    event_adsb();
  }
  event_radar();
  event_ellipsoid();

});

/**
 * @brief Adds a point to the map with the specified parameters.
 * @param {number} latitude - The latitude of the point in degrees.
 * @param {number} longitude - The longitude of the point in degrees.
 * @param {number} altitude - The altitude of the point in metres (stored as a
 *   feature property for reference; the map view is 2-D).
 * @param {string} pointName - The name of the point.
 * @param {string} pointColor - The colour of the point as a CSS color string.
 * @param {number} pointSize - The diameter of the rendered circle in pixels.
 * @param {string} type - The entity type (e.g. "radar", "adsb", "detection",
 *   "ellipsoids").
 * @param {number} timestamp - The UNIX timestamp in milliseconds when the
 *   point was added.
 * @returns {object} The GeoJSON Feature representing the added point.
 */
function addPoint(latitude, longitude, altitude, pointName, pointColor, pointSize, type, timestamp) {
  const id = type + '_' + timestamp + '_' + Math.random().toString(36).substring(2, 11);
  const feature = {
    type: 'Feature',
    id: id,
    geometry: { type: 'Point', coordinates: [longitude, latitude] },
    properties: {
      id: id,
      name: pointName,
      type: type,
      timestamp: timestamp,
      color: pointColor,
      size: pointSize,
      opacity: 1.0,
      altitude: altitude,
    },
  };
  pointFeatures.push(feature);
  updateMapSource();
  return feature;
}

// timer handle used to debounce updateMapSource() calls
var _updateSourceTimer = null;

/**
 * @brief Schedules a GeoJSON source update for the next event-loop tick.
 * Multiple addPoint() calls within the same synchronous block are batched
 * into a single setData() call, avoiding redundant GPU uploads per tick.
 */
function updateMapSource() {
  if (_updateSourceTimer !== null) return;
  _updateSourceTimer = setTimeout(function() {
    _updateSourceTimer = null;
    var source = map.getSource('points');
    if (source) {
      source.setData({ type: 'FeatureCollection', features: pointFeatures });
    }
  }, 0);
}

function is_localhost(ip) {

  // strip scheme
  ip = ip.replace(/^https?:\/\//, "");

  // strip path
  ip = ip.split('/')[0];

  // handle IPv6 bracketed notation: [::1]:8080 -> ::1
  if (ip.startsWith('[')) {
    ip = ip.split(']')[0].slice(1);
  } else if ((ip.match(/:/g) || []).length === 1) {
    // IPv4 or hostname with a single colon: strip port
    ip = ip.split(':')[0];
  }
  // bare IPv6 (multiple colons, no brackets): leave as-is

  // check for localhost hostname (after normalization to catch localhost:port)
  if (ip === 'localhost') {
    return true;
  }

  // check for IPv6 loopback
  if (ip === '::1') {
    return true;
  }

  const localRanges = ['127.0.0.1', '192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12'];

  const ipToInt = ip => ip.split('.').reduce((acc, octet) => (acc << 8) + +octet, 0) >>> 0;

  return localRanges.some(range => {
    const [rangeStart, rangeSize = 32] = range.split('/');
    const start = ipToInt(rangeStart);
    const end = (start | ((1 << (32 - +rangeSize)) - 1)) >>> 0;
    return ipToInt(ip) >= start && ipToInt(ip) <= end;
  });

}

function removeEntitiesOlderThan(entityType, maxAgeSeconds) {

  var now = Date.now();
  pointFeatures = pointFeatures.filter(function(f) {
    if (f.properties.type !== entityType) return true;
    return (now - f.properties.timestamp) <= maxAgeSeconds * 1000;
  });
  updateMapSource();

}

function removeEntitiesOlderThanAndFade(entityType, maxAgeSeconds, baseAlpha) {

  var now = Date.now();
  pointFeatures = pointFeatures.filter(function(f) {
    if (f.properties.type !== entityType) return true;
    var age = now - f.properties.timestamp;
    if (age > maxAgeSeconds * 1000) return false;
    f.properties.opacity = baseAlpha * (1 - age / (maxAgeSeconds * 1000));
    return true;
  });
  updateMapSource();

}

function removeEntitiesByType(entityType) {

  pointFeatures = pointFeatures.filter(function(f) {
    return f.properties.type !== entityType;
  });
  updateMapSource();

}

function doesEntityNameExist(name) {
  return pointFeatures.some(function(f) {
    return f.properties.name === name;
  });
}

/**
 * @brief Switches the base tile layer to the named provider.
 * @param {string} layerName - Key from config map.tile_server
 *   (e.g. "osm", "carto_dark").
 */
function switchTileLayer(layerName) {
  if (!tileUrls[layerName] || !mapLoaded) return;
  for (var name in tileUrls) {
    map.setLayoutProperty(
      'layer-' + name,
      'visibility',
      name === layerName ? 'visible' : 'none'
    );
  }
  currentTileLayer = layerName;
  document.querySelectorAll('#layer-switcher button').forEach(function(btn) {
    btn.classList.toggle('active', btn.id === 'btn-' + layerName);
  });
}