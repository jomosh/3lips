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
