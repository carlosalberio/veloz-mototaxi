const bookingForm = document.getElementById('booking-form');
const otherPassengerNameInput = document.getElementById('other-passenger-name');
const otherPassengerPhoneInput = document.getElementById('other-passenger-phone');
const otherPassengerFields = document.getElementById('other-passenger-fields');
const toggleOtherPassengerButton = document.getElementById('toggle-other-passenger');
const cancelOtherPassengerButton = document.getElementById('cancel-other-passenger');
const feedback = document.getElementById('form-feedback');
const pickupInput = document.getElementById('pickup');
const destinationInput = document.getElementById('destination');
const pickupSuggestions = document.getElementById('pickup-suggestions');
const destinationSuggestions = document.getElementById('destination-suggestions');
const pickupStatus = document.getElementById('pickup-status');
const destinationStatus = document.getElementById('destination-status');
const otherPassengerStatus = document.getElementById('other-passenger-status');
const customerProfileCompletion = document.getElementById('customer-profile-completion');
const customerProfileMessage = document.getElementById('customer-profile-message');
const customerProfileFields = document.getElementById('customer-profile-fields');
const updateCustomerProfileButton = document.getElementById('update-customer-profile');
const customerProfileFeedback = document.getElementById('customer-profile-feedback');
const confirmationDialog = document.getElementById('ride-confirmation');
const confirmationSummary = document.getElementById('ride-confirmation-summary');
const confirmationFeedback = document.getElementById('confirmation-feedback');
const confirmRideButton = document.getElementById('confirm-ride');
const editRideButton = document.getElementById('edit-ride');
const rideStatusSection = document.getElementById('ride-status');
const rideStatusTitle = document.getElementById('ride-status-title');
const rideStatusMessage = document.getElementById('ride-status-message');
const rideStatusSummary = document.getElementById('ride-status-summary');
const cancelRideButton = document.getElementById('cancel-ride');
const requestAnotherButton = document.getElementById('request-another');
const currentLocationButton = document.getElementById('use-current-location');
const mapStatus = document.getElementById('map-status');
const mapFallback = document.getElementById('map-fallback');
const accountTabs = document.querySelectorAll('.account-tab');
const authSection = document.getElementById('auth-section');
const authCard = document.getElementById('auth-card');
const closeAuthButton = document.getElementById('close-auth');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');
const loginForm = document.getElementById('auth-login-form');
const registerForm = document.getElementById('auth-register-form');
const authNavLogin = document.getElementById('auth-nav-login');
const authNavRegister = document.getElementById('auth-nav-register');
const linkToRegister = document.getElementById('link-to-register');
const linkToLogin = document.getElementById('link-to-login');
const driverRegistration = document.getElementById('driver-registration');
const authFeedback = document.getElementById('auth-feedback');
const welcomeMessage = document.getElementById('welcome-message');
const openAccountButton = document.getElementById('open-account');
const logoutButton = document.getElementById('logout-button');
const openBookingButton = document.getElementById('open-booking');
const openDeliveryButton = document.getElementById('open-delivery');
const serviceTabPassenger = document.getElementById('service-tab-passenger');
const serviceTabOrder = document.getElementById('service-tab-order');
const bookingEyebrow = document.getElementById('booking-eyebrow');
const bookingTitle = document.getElementById('booking-title');
const pickupLabel = document.getElementById('pickup-label');
const destinationLabel = document.getElementById('destination-label');
const fareTitle = document.getElementById('fare-title');
const bookingFormNote = document.getElementById('booking-form-note');
const bookingSection = document.getElementById('pedir-corrida');
const closeBookingButton = document.getElementById('close-booking');
let currentServiceType = 'passageiro';
let accountType = 'cliente';
let authSubmitting = false;
let rideSubmitting = false;
let currentRide = null;
let rideStatusTimer = null;
let passengerDisclosureTimer = null;
let forAnotherPerson = false;
let rideMap = null;
let lastGeocoderRequestAt = 0;
let pickupSelectionRevision = 0;
let automaticPickupLocationRequested = false;
let authenticatedCustomer = null;
const createIdempotencyKey = () => {
  if (typeof window.crypto?.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hexadecimal = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hexadecimal.slice(0, 8)}-${hexadecimal.slice(8, 12)}-${hexadecimal.slice(12, 16)}-${hexadecimal.slice(16, 20)}-${hexadecimal.slice(20)}`;
};
let rideIdempotencyKey = createIdempotencyKey();
const isAuthPage = document.body.classList.contains('auth-page');

const mapLocations = {
  pickup: {
    input: pickupInput,
    suggestions: pickupSuggestions,
    status: pickupStatus,
    marker: null,
    selection: null,
    timer: null,
    request: 0,
    controller: null,
  },
  destination: {
    input: destinationInput,
    suggestions: destinationSuggestions,
    status: destinationStatus,
    marker: null,
    selection: null,
    timer: null,
    request: 0,
    controller: null,
  },
};

const validatePhoneInput = (input) => {
  const digits = input.value.replace(/\D/g, '');
  input.setCustomValidity(
    digits.length === 0 || digits.length === 10 || digits.length === 11
      ? ''
      : 'Informe um telefone com DDD.',
  );
};

const phoneDigits = (value) => {
  const digits = value.replace(/\D/g, '');
  if (digits.startsWith('55') && digits.length === 13) {
    return digits.slice(2);
  }
  return digits;
};

const formatBrazilianMobile = (value) => {
  const digits = phoneDigits(value);
  if (!digits) return '';
  if (digits.length > 11) return digits;
  if (digits.length <= 2) return `(${digits}`;
  if (digits.length <= 7) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
  return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
};

const missingCustomerProfileFields = (user) => {
  const missing = [];
  if (String(user?.name || '').trim().length < 2) missing.push('name');
  if (phoneDigits(String(user?.phone || '')).length !== 11) missing.push('phone');
  return missing;
};

if (otherPassengerPhoneInput instanceof HTMLInputElement) {
  otherPassengerPhoneInput.title = 'Informe o celular da pessoa com DDD e 11 dígitos.';
  otherPassengerPhoneInput.addEventListener('input', () => {
    const formatted = formatBrazilianMobile(otherPassengerPhoneInput.value);
    otherPassengerPhoneInput.value = formatted;
    const validPhone = phoneDigits(formatted).length === 11;
    otherPassengerPhoneInput.setCustomValidity(
      validPhone ? '' : 'Informe um celular brasileiro com DDD e 11 dígitos.',
    );
    if (validPhone) {
      setFieldStatus(otherPassengerStatus, 'Celular válido para contato.', 'success');
    } else {
      setFieldStatus(otherPassengerStatus, 'Informe um celular brasileiro com DDD e 11 dígitos.', 'error');
    }
  });
}

if (otherPassengerNameInput instanceof HTMLInputElement) {
  otherPassengerNameInput.addEventListener('input', () => {
    const validName = otherPassengerNameInput.value.trim().length >= 2;
    otherPassengerNameInput.setCustomValidity(
      validName ? '' : 'Informe o nome completo do passageiro.',
    );
  });
}

const registerPhoneInput = registerForm?.querySelector('[name="phone"]');
if (registerPhoneInput instanceof HTMLInputElement) {
  registerPhoneInput.title = 'Informe um telefone com DDD.';
  registerPhoneInput.addEventListener('input', () => validatePhoneInput(registerPhoneInput));
}

const isForAnotherPerson = () => forAnotherPerson;

const updatePassengerMode = (isOther, clearThirdParty = false) => {
  forAnotherPerson = isOther;
  if (passengerDisclosureTimer) {
    window.clearTimeout(passengerDisclosureTimer);
    passengerDisclosureTimer = null;
  }
  if (toggleOtherPassengerButton instanceof HTMLButtonElement) {
    toggleOtherPassengerButton.hidden = isOther;
    toggleOtherPassengerButton.setAttribute('aria-expanded', String(isOther));
  }
  if (otherPassengerFields instanceof HTMLElement) {
    otherPassengerFields.setAttribute('aria-hidden', String(!isOther));
  }
  if (otherPassengerNameInput instanceof HTMLInputElement) {
    otherPassengerNameInput.disabled = !isOther;
    otherPassengerNameInput.required = isOther;
    if (clearThirdParty) {
      otherPassengerNameInput.value = '';
      otherPassengerNameInput.setCustomValidity('');
    }
  }
  if (otherPassengerPhoneInput instanceof HTMLInputElement) {
    otherPassengerPhoneInput.disabled = !isOther;
    otherPassengerPhoneInput.required = isOther;
    if (clearThirdParty) {
      otherPassengerPhoneInput.value = '';
      otherPassengerPhoneInput.setCustomValidity('');
      setFieldStatus(otherPassengerStatus, '');
    }
  }
  if (cancelOtherPassengerButton instanceof HTMLButtonElement) {
    cancelOtherPassengerButton.disabled = !isOther;
  }
  if (otherPassengerFields instanceof HTMLElement) {
    if (isOther) {
      otherPassengerFields.hidden = false;
      window.requestAnimationFrame(() => {
        if (forAnotherPerson) otherPassengerFields.classList.add('is-expanded');
      });
    } else {
      otherPassengerFields.classList.remove('is-expanded');
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        otherPassengerFields.hidden = true;
      } else {
        passengerDisclosureTimer = window.setTimeout(() => {
          if (!forAnotherPerson) otherPassengerFields.hidden = true;
        }, 260);
      }
    }
  }
  if (authenticatedCustomer) {
    renderCustomerProfileCompletion(authenticatedCustomer);
  }
};

if (toggleOtherPassengerButton instanceof HTMLButtonElement) {
  toggleOtherPassengerButton.addEventListener('click', () => {
    updatePassengerMode(true);
    window.requestAnimationFrame(() => otherPassengerNameInput?.focus());
  });
}

if (cancelOtherPassengerButton instanceof HTMLButtonElement) {
  cancelOtherPassengerButton.addEventListener('click', () => {
    updatePassengerMode(false, true);
    toggleOtherPassengerButton?.focus();
  });
}

const setServiceType = (type) => {
  currentServiceType = type === 'pedido' ? 'pedido' : 'passageiro';
  const isOrder = currentServiceType === 'pedido';

  if (serviceTabPassenger) {
    serviceTabPassenger.classList.toggle('is-active', !isOrder);
    serviceTabPassenger.setAttribute('aria-selected', String(!isOrder));
  }
  if (serviceTabOrder) {
    serviceTabOrder.classList.toggle('is-active', isOrder);
    serviceTabOrder.setAttribute('aria-selected', String(isOrder));
  }

  if (bookingEyebrow) {
    bookingEyebrow.textContent = isOrder ? 'TRANSPORTE DE ENCOMENDAS' : 'SUA PRÓXIMA VIAGEM';
  }
  if (bookingTitle) {
    bookingTitle.textContent = isOrder ? 'Envie seu pedido aqui' : 'Peça sua corrida aqui';
  }
  if (pickupLabel) {
    pickupLabel.textContent = isOrder ? 'Endereço de retirada' : 'Onde vamos te buscar?';
  }
  if (destinationLabel) {
    destinationLabel.textContent = isOrder ? 'Endereço de entrega' : 'Para onde você vai?';
  }
  if (pickupInput instanceof HTMLInputElement) {
    pickupInput.placeholder = isOrder
      ? 'Digite o local onde o mototaxista retira o pacote'
      : 'Digite rua, número ou estabelecimento';
  }
  if (destinationInput instanceof HTMLInputElement) {
    destinationInput.placeholder = isOrder
      ? 'Digite o local onde o pacote deve ser entregue'
      : 'Pesquise o destino';
  }
  const pickupHelp = document.getElementById('pickup-help');
  if (pickupHelp) {
    pickupHelp.textContent = isOrder
      ? 'Informe onde o mototaxista deve retirar a encomenda.'
      : 'Ao abrir o formulário, vamos detectar sua localização. Você pode editar o endereço ou escolher outro ponto no mapa.';
  }
  if (fareTitle) {
    fareTitle.textContent = isOrder ? 'Tarifa fixa do envio' : 'Tarifa fixa da corrida';
  }
  if (bookingFormNote) {
    bookingFormNote.innerHTML = isOrder
      ? '<span aria-hidden="true">📦</span> Seus dados cadastrados são usados para o envio do pedido.'
      : '<span aria-hidden="true">♧</span> Seus dados são usados somente para organizar sua corrida.';
  }

  if (toggleOtherPassengerButton instanceof HTMLButtonElement) {
    toggleOtherPassengerButton.hidden = isOrder || forAnotherPerson;
  }
  if (isOrder && forAnotherPerson) {
    updatePassengerMode(false, true);
  }
};

const openBookingModal = (serviceType = 'passageiro') => {
  setServiceType(serviceType);
  if (bookingSection instanceof HTMLElement) {
    bookingSection.hidden = false;
    openBookingButton?.setAttribute('aria-expanded', 'true');
    openDeliveryButton?.setAttribute('aria-expanded', 'true');
    bookingSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (!automaticPickupLocationRequested && !mapLocations.pickup.selection) {
      automaticPickupLocationRequested = true;
      captureCurrentPickupLocation();
    }
    window.requestAnimationFrame(() => {
      if (rideMap) rideMap.invalidateSize();
      if (pickupInput instanceof HTMLInputElement) pickupInput.focus();
    });
  }
};

if (openBookingButton instanceof HTMLElement) {
  openBookingButton.addEventListener('click', () => openBookingModal('passageiro'));
}

if (openDeliveryButton instanceof HTMLElement) {
  openDeliveryButton.addEventListener('click', () => openBookingModal('pedido'));
}

if (serviceTabPassenger instanceof HTMLButtonElement) {
  serviceTabPassenger.addEventListener('click', () => setServiceType('passageiro'));
}

if (serviceTabOrder instanceof HTMLButtonElement) {
  serviceTabOrder.addEventListener('click', () => setServiceType('pedido'));
}

if (window.location.hash === '#enviar-pedido') {
  window.addEventListener('DOMContentLoaded', () => openBookingModal('pedido'));
}

if (
  closeBookingButton instanceof HTMLButtonElement
  && bookingSection instanceof HTMLElement
) {
  closeBookingButton.addEventListener('click', () => {
    bookingSection.hidden = true;
    openBookingButton?.setAttribute('aria-expanded', 'false');
    openDeliveryButton?.setAttribute('aria-expanded', 'false');
    openBookingButton?.focus();
  });
}

const formatCurrency = (value) => new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
}).format(value);

const requestApi = async (path, options = {}) => {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      credentials: 'same-origin',
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error('Não foi possível conectar ao servidor. Inicie o backend do Veloz e tente novamente.');
  }

  let result = {};
  try {
    result = await response.json();
  } catch {
    result = {};
  }

  if (!response.ok) {
    const detail = result.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(' ')
      : detail;
    const error = new Error(message || 'Não foi possível concluir a solicitação.');
    error.status = response.status;
    throw error;
  }
  return result;
};

const setFieldStatus = (element, message, state = '') => {
  if (!(element instanceof HTMLElement)) return;
  element.textContent = message;
  if (state) {
    element.dataset.state = state;
  } else {
    delete element.dataset.state;
  }
};

const setSuggestionMessage = (element, message) => {
  if (!(element instanceof HTMLElement)) return;
  const paragraph = document.createElement('p');
  paragraph.textContent = message;
  element.replaceChildren(paragraph);
  element.hidden = false;
};

const addressLabelFromFeature = (feature) => {
  const properties = feature?.properties || {};
  const street = [properties.street, properties.housenumber]
    .filter(Boolean)
    .join(', ');
  const parts = [
    properties.name,
    street,
    properties.district || properties.suburb,
    properties.city || properties.town || properties.village,
    properties.state,
  ]
    .map((part) => String(part || '').trim())
    .filter(Boolean);
  return parts.filter((part, index) => parts.indexOf(part) === index).join(' · ');
};

const normalizeGeocoderText = (value) => String(value || '')
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .trim()
  .toLowerCase();

const isSerraTalhadaFeature = (feature) => {
  const properties = feature?.properties || {};
  const localities = [
    properties.city,
    properties.town,
    properties.village,
    properties.municipality,
    properties.county,
    properties.district,
  ].map(normalizeGeocoderText);
  return localities.includes('serra talhada')
    && normalizeGeocoderText(properties.state) === 'pernambuco'
    && ['brasil', 'brazil'].includes(normalizeGeocoderText(properties.country));
};

const normalizedGeocodeFeature = (feature) => {
  const coordinates = feature?.geometry?.coordinates;
  if (!isSerraTalhadaFeature(feature) || !Array.isArray(coordinates) || coordinates.length < 2) return null;
  const longitude = Number(coordinates[0]);
  const latitude = Number(coordinates[1]);
  const label = addressLabelFromFeature(feature);
  if (
    !label
    || !Number.isFinite(latitude)
    || !Number.isFinite(longitude)
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
  ) {
    return null;
  }
  return { label, lat: latitude, lng: longitude };
};

const requestPhoton = async (url, signal) => {
  const delay = Math.max(0, 1000 - (Date.now() - lastGeocoderRequestAt));
  if (delay) await new Promise((resolve) => window.setTimeout(resolve, delay));
  if (signal?.aborted) throw new DOMException('Busca cancelada.', 'AbortError');
  lastGeocoderRequestAt = Date.now();
  let response;
  try {
    response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('O serviço de endereços não respondeu. Tente novamente.');
  }
  if (!response.ok) {
    throw new Error('Não foi possível consultar os endereços agora. Tente novamente.');
  }
  try {
    return await response.json();
  } catch {
    throw new Error('O serviço de endereços retornou uma resposta inválida.');
  }
};

const updateMapStatus = () => {
  if (!(mapStatus instanceof HTMLElement)) return;
  const selectedCount = Object.values(mapLocations)
    .filter((location) => location.selection)
    .length;
  if (!rideMap) {
    mapStatus.textContent = 'O mapa não carregou. Pesquise e selecione endereços para validar o trajeto.';
  } else if (selectedCount === 0) {
    mapStatus.textContent = 'Pesquise e selecione os endereços para marcá-los no mapa.';
  } else if (selectedCount === 1) {
    mapStatus.textContent = 'Um local selecionado. Selecione o outro endereço para concluir o trajeto.';
  } else {
    mapStatus.textContent = 'Origem e destino selecionados e marcados no mapa.';
  }
};

const updateMapView = () => {
  if (!rideMap) return;
  const selected = Object.values(mapLocations)
    .map((location) => location.selection)
    .filter(Boolean);
  if (selected.length > 1) {
    const bounds = window.L.latLngBounds(selected.map((location) => [location.lat, location.lng]));
    rideMap.fitBounds(bounds, { padding: [36, 36], maxZoom: 15 });
  } else if (selected.length === 1) {
    rideMap.setView([selected[0].lat, selected[0].lng], 15);
  }
};

const selectMapLocation = (kind, selection, message = 'Endereço selecionado e marcado no mapa.') => {
  const location = mapLocations[kind];
  if (!location || !(location.input instanceof HTMLInputElement)) return;
  if (kind === 'pickup') pickupSelectionRevision += 1;
  location.selection = selection;
  location.input.value = selection.label;
  location.input.setCustomValidity('');
  location.suggestions.hidden = true;
  setFieldStatus(location.status, message, 'success');

  if (location.marker && rideMap) rideMap.removeLayer(location.marker);
  if (rideMap) {
    const color = kind === 'pickup' ? '#728d21' : '#db7048';
    const popup = document.createElement('span');
    popup.textContent = selection.label;
    location.marker = window.L.circleMarker([selection.lat, selection.lng], {
      radius: 9,
      color,
      fillColor: color,
      fillOpacity: 0.9,
      weight: 2,
    }).addTo(rideMap);
    location.marker.bindPopup(popup);
  }
  updateMapView();
  updateMapStatus();
};

const clearMapLocation = (kind) => {
  const location = mapLocations[kind];
  if (!location) return;
  location.selection = null;
  if (location.marker && rideMap) rideMap.removeLayer(location.marker);
  location.marker = null;
  updateMapStatus();
};

const renderAddressSuggestions = (kind, features) => {
  const location = mapLocations[kind];
  if (!location || !(location.suggestions instanceof HTMLElement)) return;
  const addresses = features
    .map(normalizedGeocodeFeature)
    .filter(Boolean);
  if (!addresses.length) {
    setSuggestionMessage(
      location.suggestions,
      'Nenhum endereço encontrado em Serra Talhada. Confira o texto e tente novamente.',
    );
    return;
  }

  const buttons = addresses.map((address, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.role = 'option';
    button.textContent = address.label;
    button.setAttribute('aria-selected', 'false');
    button.addEventListener('click', () => {
      selectMapLocation(kind, address);
      location.input.focus();
    });
    button.addEventListener('keydown', (event) => {
      const options = [...location.suggestions.querySelectorAll('button')];
      const currentIndex = options.indexOf(button);
      if (event.key === 'ArrowDown' && options[currentIndex + 1]) {
        event.preventDefault();
        options[currentIndex + 1].focus();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (options[currentIndex - 1]) options[currentIndex - 1].focus();
        else location.input.focus();
      } else if (event.key === 'Escape') {
        location.suggestions.hidden = true;
        location.input.focus();
      }
    });
    button.dataset.optionIndex = String(index);
    return button;
  });
  location.suggestions.replaceChildren(...buttons);
  location.suggestions.hidden = false;
};

const searchAddress = async (kind, query, requestNumber, signal) => {
  try {
    const result = await requestPhoton(
      `https://photon.komoot.io/api/?q=${encodeURIComponent(`${query}, Serra Talhada, Pernambuco`)}&limit=5&lat=-7.9867805&lon=-38.2920294&zoom=13`,
      signal,
    );
    const location = mapLocations[kind];
    if (!location || location.request !== requestNumber || signal.aborted) return;
    renderAddressSuggestions(kind, Array.isArray(result.features) ? result.features : []);
    setFieldStatus(location.status, '');
  } catch (error) {
    const location = mapLocations[kind];
    if (!location || location.request !== requestNumber || error.name === 'AbortError') return;
    setSuggestionMessage(location.suggestions, error.message);
    setFieldStatus(location.status, 'A busca de endereços está temporariamente indisponível.', 'error');
  }
};

Object.entries(mapLocations).forEach(([kind, location]) => {
  if (!(location.input instanceof HTMLInputElement)) return;
  location.input.addEventListener('input', () => {
    if (kind === 'pickup') pickupSelectionRevision += 1;
    if (location.selection && location.input.value.trim() === location.selection.label) return;
    clearMapLocation(kind);
    location.input.setCustomValidity('');
    if (location.timer) window.clearTimeout(location.timer);
    if (location.controller) location.controller.abort();
    location.request += 1;
    const requestNumber = location.request;
    const query = location.input.value.trim();
    if (query.length < 3) {
      location.suggestions.hidden = true;
      setFieldStatus(location.status, query ? 'Digite ao menos 3 caracteres para pesquisar.' : '');
      return;
    }

    setSuggestionMessage(location.suggestions, 'Consultando endereços reais…');
    setFieldStatus(location.status, 'Buscando sugestões de endereço…');
    location.controller = new AbortController();
    location.timer = window.setTimeout(() => {
      void searchAddress(kind, query, requestNumber, location.controller.signal);
    }, 650);
  });

  location.input.addEventListener('keydown', (event) => {
    const firstOption = location.suggestions.querySelector('button');
    if (event.key === 'ArrowDown' && firstOption && !location.suggestions.hidden) {
      event.preventDefault();
      firstOption.focus();
    } else if (event.key === 'Enter' && firstOption && !location.suggestions.hidden) {
      event.preventDefault();
      firstOption.click();
    } else if (event.key === 'Escape') {
      location.suggestions.hidden = true;
    }
  });
});

if (typeof window.L !== 'undefined') {
  const serviceAreaBounds = window.L.latLngBounds(
    [-8.4385, -38.6276],
    [-7.6784, -38.0282],
  );
  rideMap = window.L.map('ride-map', {
    scrollWheelZoom: false,
    maxBounds: serviceAreaBounds,
    maxBoundsViscosity: 0.8,
  }).setView([-7.9867805, -38.2920294], 13);
  window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(rideMap);
  if (mapFallback instanceof HTMLElement) mapFallback.hidden = true;
} else if (mapFallback instanceof HTMLElement) {
  mapFallback.textContent = 'O mapa não carregou. Pesquise e selecione endereços para validar a localização.';
}
updateMapStatus();

const captureCurrentPickupLocation = () => {
  if (!navigator.geolocation) {
    setFieldStatus(pickupStatus, 'Este navegador não oferece localização. Pesquise o endereço manualmente.', 'error');
    return;
  }
  if (currentLocationButton instanceof HTMLButtonElement) {
    currentLocationButton.disabled = true;
  }
  const revisionAtStart = pickupSelectionRevision;
  setFieldStatus(pickupStatus, 'Aguardando permissão de localização…');
  navigator.geolocation.getCurrentPosition(
    async ({ coords }) => {
      try {
        if (pickupSelectionRevision !== revisionAtStart) {
          setFieldStatus(pickupStatus, 'Endereço mantido conforme sua escolha.', 'success');
          return;
        }
        const latitude = coords.latitude;
        const longitude = coords.longitude;
        const result = await requestPhoton(
          `https://photon.komoot.io/reverse?lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`,
        );
        if (pickupSelectionRevision !== revisionAtStart) {
          setFieldStatus(pickupStatus, 'Endereço mantido conforme sua escolha.', 'success');
          return;
        }
        const localFeature = Array.isArray(result.features)
          ? result.features.find(isSerraTalhadaFeature)
          : null;
        const reverseResult = normalizedGeocodeFeature(localFeature);
        if (!reverseResult) {
          throw new Error('Sua localização atual não foi confirmada dentro de Serra Talhada.');
        }
        selectMapLocation(
          'pickup',
          { ...reverseResult, lat: latitude, lng: longitude },
          'Localização atual selecionada. Edite o endereço ou escolha outro ponto no mapa se preferir.',
        );
      } catch (error) {
        setFieldStatus(pickupStatus, error.message, 'error');
      } finally {
        if (currentLocationButton instanceof HTMLButtonElement) {
          currentLocationButton.disabled = false;
        }
      }
    },
    (error) => {
      const message = error.code === error.PERMISSION_DENIED
        ? 'Permissão de localização negada. Pesquise o endereço manualmente.'
        : error.code === error.TIMEOUT
          ? 'A localização demorou demais. Tente novamente ou pesquise o endereço.'
          : 'Não foi possível obter sua localização. Pesquise o endereço manualmente.';
      setFieldStatus(pickupStatus, message, 'error');
      if (currentLocationButton instanceof HTMLButtonElement) {
        currentLocationButton.disabled = false;
      }
    },
    { enableHighAccuracy: true, maximumAge: 60_000, timeout: 10_000 },
  );
};

if (currentLocationButton instanceof HTMLButtonElement) {
  currentLocationButton.addEventListener('click', captureCurrentPickupLocation);
}

const showAuthFeedback = (message, state = 'error') => {
  if (authFeedback instanceof HTMLParagraphElement) {
    authFeedback.textContent = message;
    authFeedback.dataset.state = state;
    authFeedback.hidden = false;
  }
};

const renderCustomerProfileCompletion = (user) => {
  if (
    !(customerProfileCompletion instanceof HTMLElement)
    || !(customerProfileFields instanceof HTMLElement)
  ) {
    return;
  }
  authenticatedCustomer = user;
  const missing = missingCustomerProfileFields(user);
  customerProfileFields.replaceChildren();
  for (const fieldName of missing) {
    const field = document.createElement('div');
    field.className = 'field';
    const inputId = `customer-profile-${fieldName}`;
    const label = document.createElement('label');
    label.htmlFor = inputId;
    label.textContent = fieldName === 'name' ? 'Nome completo' : 'Celular com DDD';
    const inputWrap = document.createElement('div');
    inputWrap.className = 'input-wrap';
    const input = document.createElement('input');
    input.id = inputId;
    input.name = fieldName;
    input.value = String(user[fieldName] || '');
    input.disabled = forAnotherPerson;
    input.required = true;
    if (fieldName === 'name') {
      input.type = 'text';
      input.autocomplete = 'name';
      input.minLength = 2;
      input.maxLength = 120;
    } else {
      input.type = 'tel';
      input.autocomplete = 'tel';
      input.inputMode = 'tel';
      input.maxLength = 15;
      input.title = 'Informe um celular brasileiro com DDD e 11 dígitos.';
      input.value = formatBrazilianMobile(input.value);
      input.addEventListener('input', () => {
        input.value = formatBrazilianMobile(input.value);
        input.setCustomValidity(
          phoneDigits(input.value).length === 11
            ? ''
            : 'Informe um celular brasileiro com DDD e 11 dígitos.',
        );
      });
    }
    inputWrap.append(input);
    field.append(label, inputWrap);
    customerProfileFields.append(field);
  }
  customerProfileCompletion.hidden = missing.length === 0 || forAnotherPerson;
  if (customerProfileMessage instanceof HTMLElement) {
    customerProfileMessage.textContent = missing.length
      ? 'Complete somente os dados ausentes para pedir uma corrida para você.'
      : '';
  }
  if (customerProfileFeedback instanceof HTMLElement) {
    customerProfileFeedback.textContent = '';
  }
};

if (
  updateCustomerProfileButton instanceof HTMLButtonElement
  && customerProfileFields instanceof HTMLElement
) {
  updateCustomerProfileButton.addEventListener('click', async () => {
    const profile = {};
    const nameInput = customerProfileFields.querySelector('#customer-profile-name');
    const phoneInput = customerProfileFields.querySelector('#customer-profile-phone');
    if (nameInput instanceof HTMLInputElement) {
      const name = nameInput.value.trim();
      nameInput.setCustomValidity(name.length >= 2 ? '' : 'Informe seu nome completo.');
      if (name.length < 2) {
        nameInput.reportValidity();
        return;
      }
      profile.name = name;
    }
    if (phoneInput instanceof HTMLInputElement) {
      phoneInput.value = formatBrazilianMobile(phoneInput.value);
      const phone = phoneDigits(phoneInput.value);
      phoneInput.setCustomValidity(
        phone.length === 11 ? '' : 'Informe um celular brasileiro com DDD e 11 dígitos.',
      );
      if (phone.length !== 11) {
        phoneInput.reportValidity();
        return;
      }
      profile.phone = phone;
    }
    updateCustomerProfileButton.disabled = true;
    try {
      const updatedProfile = await requestApi('/api/customer/profile', {
        method: 'PUT',
        body: JSON.stringify(profile),
      });
      authenticatedCustomer = { ...authenticatedCustomer, ...updatedProfile };
      renderCustomerProfileCompletion(authenticatedCustomer);
      if (feedback instanceof HTMLElement) {
        feedback.textContent = missingCustomerProfileFields(authenticatedCustomer).length
          ? 'Dados atualizados. Complete o outro dado solicitado.'
          : 'Dados atualizados; a corrida usará as informações da sua conta.';
        feedback.dataset.state = 'success';
        feedback.hidden = false;
      }
    } catch (error) {
      if (customerProfileFeedback instanceof HTMLElement) {
        customerProfileFeedback.textContent = error.message;
        customerProfileFeedback.dataset.state = 'error';
      }
    } finally {
      updateCustomerProfileButton.disabled = false;
    }
  });
}

const finishAccountEntry = (user) => {
  if (user.accountType === 'cliente') {
    renderCustomerProfileCompletion(user);
  } else {
    authenticatedCustomer = null;
  }
  if (openAccountButton instanceof HTMLElement) {
    openAccountButton.hidden = true;
  }
  if (welcomeMessage instanceof HTMLParagraphElement) {
    welcomeMessage.textContent = `Olá, ${user.name}.`;
    welcomeMessage.hidden = false;
  }
  if (logoutButton instanceof HTMLButtonElement) {
    logoutButton.hidden = false;
  }
  if (openBookingButton instanceof HTMLElement) {
    openBookingButton.hidden = user.accountType !== 'cliente';
  }
  if (openDeliveryButton instanceof HTMLElement) {
    openDeliveryButton.hidden = user.accountType !== 'cliente';
  }
};

const restoreAccountSession = async () => {
  try {
    const result = await requestApi('/api/me');
    if (result.user) {
      if (isAuthPage) {
        window.location.replace(
          result.user.accountType === 'mototaxista'
            ? '/painel'
            : result.user.accountType === 'admin'
              ? '/admin-entregas'
              : '/inicio',
        );
        return;
      }
      finishAccountEntry(result.user);
    }
  } catch (error) {
    if (isAuthPage) {
      showAuthFeedback(error.message);
    } else {
      console.error(error);
    }
  }
};

const setAuthFormBusy = (form, busy, loadingLabel) => {
  const button = form.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) return;

  const label = button.querySelector('[data-submit-label]');
  if (label instanceof HTMLElement) {
    if (!button.dataset.idleLabel) {
      button.dataset.idleLabel = label.textContent.trim();
    }
    label.textContent = busy ? loadingLabel : button.dataset.idleLabel;
  }
  button.disabled = busy;
  button.setAttribute('aria-busy', String(busy));
  form.setAttribute('aria-busy', String(busy));
};

const updateDriverFields = () => {
  if (driverRegistration instanceof HTMLDivElement) {
    const isDriver = accountType === 'mototaxista';
    driverRegistration.hidden = !isDriver;

    driverRegistration.querySelectorAll('input, select').forEach((field) => {
      if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
        const requiredDriverFields = [
          'cpf',
          'cnh',
          'cnhCategory',
          'cnhExpiry',
          'motorcycle',
          'plate',
        ];
        const isRequired = isDriver && requiredDriverFields.includes(field.name);
        field.required = isRequired;
        const isRegisterActive = registerForm instanceof HTMLFormElement && !registerForm.hidden;
        field.disabled = !isRegisterActive || !isDriver;
      }
    });
  }
};

const setAccountType = (type) => {
  accountType = type === 'mototaxista' ? 'mototaxista' : 'cliente';
  accountTabs.forEach((item) => {
    const isSelected = (item.dataset.accountType || 'cliente') === accountType;
    item.classList.toggle('is-active', isSelected);
    item.setAttribute('aria-selected', isSelected ? 'true' : 'false');
  });
  updateDriverFields();
  if (authFeedback instanceof HTMLParagraphElement) {
    authFeedback.hidden = true;
  }
};

const setAuthMode = (mode = 'login') => {
  const isRegister = mode === 'cadastro';

  if (authCard instanceof HTMLElement) {
    authCard.classList.toggle('auth-card-register', isRegister);
  }
  if (authTitle instanceof HTMLElement) {
    authTitle.textContent = isRegister ? 'Crie sua conta' : 'Bem-vindo de volta';
  }
  if (authSubtitle instanceof HTMLElement) {
    authSubtitle.textContent = isRegister
      ? 'Preencha seus dados para começar.'
      : 'Entre na sua conta para continuar.';
  }

  if (loginForm instanceof HTMLFormElement) {
    loginForm.hidden = isRegister;
    loginForm.querySelectorAll('input, button').forEach((el) => {
      if (el instanceof HTMLInputElement || el instanceof HTMLButtonElement) {
        el.disabled = isRegister;
      }
    });
  }

  if (registerForm instanceof HTMLFormElement) {
    registerForm.hidden = !isRegister;
    registerForm.querySelectorAll('input, select, button').forEach((el) => {
      if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLButtonElement) {
        el.disabled = !isRegister;
      }
    });
    if (isRegister) {
      updateDriverFields();
    }
  }

  if (authNavLogin instanceof HTMLElement) {
    authNavLogin.hidden = isRegister;
  }
  if (authNavRegister instanceof HTMLElement) {
    authNavRegister.hidden = !isRegister;
  }
  if (authFeedback instanceof HTMLParagraphElement) {
    authFeedback.hidden = true;
    authFeedback.textContent = '';
  }
};

const openAuthModal = (mode = 'login', targetAccountType = null) => {
  if (targetAccountType) {
    setAccountType(targetAccountType);
  }
  setAuthMode(mode);
  if (authSection instanceof HTMLElement) {
    authSection.hidden = false;
    openAccountButton?.setAttribute('aria-expanded', 'true');
    authSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.requestAnimationFrame(() => {
      if (mode === 'cadastro') {
        const firstInput = registerForm?.querySelector('input:not([disabled])');
        if (firstInput instanceof HTMLInputElement) firstInput.focus();
      } else {
        const firstInput = loginForm?.querySelector('input:not([disabled])');
        if (firstInput instanceof HTMLInputElement) firstInput.focus();
      }
    });
  }
};

const closeAuthModal = () => {
  if (authSection instanceof HTMLElement) {
    authSection.hidden = true;
    openAccountButton?.setAttribute('aria-expanded', 'false');
    openAccountButton?.focus();
  }
};

if (openAccountButton instanceof HTMLElement) {
  openAccountButton.addEventListener('click', () => {
    openAuthModal('login');
  });
}

if (closeAuthButton instanceof HTMLElement) {
  closeAuthButton.addEventListener('click', closeAuthModal);
}

if (linkToRegister instanceof HTMLElement) {
  linkToRegister.addEventListener('click', (event) => {
    event.preventDefault();
    setAuthMode('cadastro');
    window.history.replaceState(null, '', '#cadastro');
    window.requestAnimationFrame(() => {
      const firstInput = registerForm?.querySelector('input:not([disabled])');
      if (firstInput instanceof HTMLInputElement) firstInput.focus();
    });
  });
}

if (linkToLogin instanceof HTMLElement) {
  linkToLogin.addEventListener('click', (event) => {
    event.preventDefault();
    setAuthMode('login');
    window.history.replaceState(null, '', '#login');
    window.requestAnimationFrame(() => {
      const firstInput = loginForm?.querySelector('input:not([disabled])');
      if (firstInput instanceof HTMLInputElement) firstInput.focus();
    });
  });
}

accountTabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    setAccountType(tab.dataset.accountType || 'cliente');
  });
});

if (loginForm instanceof HTMLFormElement) {
  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (authSubmitting) return;
    if (!loginForm.reportValidity()) return;

    authSubmitting = true;
    setAuthFormBusy(loginForm, true, 'Entrando...');
    const formData = new FormData(loginForm);
    try {
      const result = await requestApi('/api/login', {
        method: 'POST',
        body: JSON.stringify({
          accountType,
          email: String(formData.get('email')).trim(),
          password: String(formData.get('password')),
        }),
      });
      if (result.user.accountType === 'mototaxista') {
        window.location.assign('/painel');
      } else if (result.user.accountType === 'admin') {
        window.location.assign('/inicio');
      } else {
        finishAccountEntry(result.user);
        closeAuthModal();
        loginForm.reset();
        window.history.replaceState(null, '', window.location.pathname);
      }
    } catch (error) {
      showAuthFeedback(error.status === 401
        ? 'E-mail ou senha inválidos. Confira seus dados e tente novamente.'
        : error.message);
    } finally {
      authSubmitting = false;
      setAuthFormBusy(loginForm, false, 'Entrando...');
    }
  });
}

if (registerForm instanceof HTMLFormElement) {
  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (authSubmitting) return;
    if (registerPhoneInput instanceof HTMLInputElement) {
      validatePhoneInput(registerPhoneInput);
    }
    if (!registerForm.reportValidity()) return;

    const formData = new FormData(registerForm);
    const name = String(formData.get('name')).trim();
    const age = Number(formData.get('age'));
    const email = String(formData.get('email')).trim().toLowerCase();
    const password = String(formData.get('password'));

    if (age < 18) {
      showAuthFeedback('É necessário ter pelo menos 18 anos.');
      return;
    }

    const user = {
      accountType,
      name,
      age,
      email,
      phone: String(formData.get('phone')).trim(),
      password,
    };

    if (accountType === 'mototaxista') {
      const cnhExpiry = String(formData.get('cnhExpiry'));
      const plate = String(formData.get('plate')).trim().toUpperCase();

      if (new Date(`${cnhExpiry}T23:59:59`) < new Date()) {
        showAuthFeedback('A CNH informada está vencida.');
        return;
      }

      Object.assign(user, {
        cpf: String(formData.get('cpf')).trim(),
        cnh: String(formData.get('cnh')).trim(),
        cnhCategory: String(formData.get('cnhCategory')),
        cnhExpiry,
        motorcycle: String(formData.get('motorcycle')).trim(),
        plate,
      });
    }

    authSubmitting = true;
    setAuthFormBusy(registerForm, true, 'Criando cadastro...');
    try {
      await requestApi('/api/register', {
        method: 'POST',
        body: JSON.stringify(user),
      });
    } catch (error) {
      showAuthFeedback(error.message);
      return;
    } finally {
      authSubmitting = false;
      setAuthFormBusy(registerForm, false, 'Criando cadastro...');
    }

    setAuthMode('login');
    const loginEmailInput = loginForm?.querySelector('#login-email');
    if (loginEmailInput instanceof HTMLInputElement) {
      loginEmailInput.value = email;
    }
    const loginPasswordInput = loginForm?.querySelector('#login-password');
    if (loginPasswordInput instanceof HTMLInputElement) {
      loginPasswordInput.value = '';
      loginPasswordInput.focus();
    }
    registerForm.reset();
    showAuthFeedback(
      'Cadastro realizado com sucesso. Entre com seu e-mail e senha para acessar a conta.',
      'success',
    );
    window.history.replaceState(null, '', '#login');
  });
}

const checkAuthUrlState = () => {
  const hash = window.location.hash.toLowerCase();
  const searchParams = new URLSearchParams(window.location.search);
  const hashQuery = window.location.hash.includes('?') ? window.location.hash.split('?')[1] : '';
  const hashParams = new URLSearchParams(hashQuery);

  const tipo = searchParams.get('tipo') || hashParams.get('tipo');
  if (tipo === 'mototaxista') {
    setAccountType('mototaxista');
  } else if (tipo === 'cliente') {
    setAccountType('cliente');
  }

  const isCadastro = hash.startsWith('#cadastro');
  const isLogin = hash.startsWith('#login');

  if (isCadastro) {
    openAuthModal('cadastro');
  } else if (isLogin) {
    openAuthModal('login');
  }

  if (searchParams.get('cadastro') === 'sucesso' || hashParams.get('cadastro') === 'sucesso') {
    openAuthModal('login');
    showAuthFeedback(
      'Cadastro realizado com sucesso. Entre com seu e-mail e senha para acessar a conta.',
      'success',
    );
  }
};

window.addEventListener('hashchange', checkAuthUrlState);
updateDriverFields();
restoreAccountSession();
checkAuthUrlState();

if (logoutButton instanceof HTMLButtonElement) {
  logoutButton.addEventListener('click', async () => {
    try {
      await requestApi('/api/logout', { method: 'POST' });
    } catch (error) {
      if (welcomeMessage instanceof HTMLParagraphElement) {
        welcomeMessage.textContent = error.message;
      }
      return;
    }

    if (openAccountButton instanceof HTMLElement) {
      openAccountButton.hidden = false;
      openAccountButton.setAttribute('aria-expanded', 'false');
    }
    if (authSection instanceof HTMLElement) {
      authSection.hidden = true;
    }
    if (welcomeMessage instanceof HTMLParagraphElement) {
      welcomeMessage.hidden = true;
    }
    if (logoutButton instanceof HTMLButtonElement) {
      logoutButton.hidden = true;
    }
    if (openBookingButton instanceof HTMLElement) {
      openBookingButton.hidden = true;
      openBookingButton.setAttribute('aria-expanded', 'false');
    }
    if (openDeliveryButton instanceof HTMLElement) {
      openDeliveryButton.hidden = true;
      openDeliveryButton.setAttribute('aria-expanded', 'false');
    }
    if (bookingSection instanceof HTMLElement) {
      bookingSection.hidden = true;
    }
  });
}

const formatBrazilianDateTime = (value) => new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
}).format(value);

const setDescriptionList = (element, items) => {
  if (!(element instanceof HTMLElement)) return;
  const nodes = [];
  items.forEach(([label, value]) => {
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value;
    nodes.push(term, description);
  });
  element.replaceChildren(...nodes);
};

const getRideDateTimeLabel = () => `Agora — ${formatBrazilianDateTime(new Date())}`;

const validateBookingInputs = () => {
  let valid = true;
  Object.entries(mapLocations).forEach(([kind, location]) => {
    const selected = location.selection
      && location.input instanceof HTMLInputElement
      && location.input.value.trim() === location.selection.label;
    if (location.input instanceof HTMLInputElement) {
      location.input.setCustomValidity(
        selected ? '' : 'Pesquise e selecione um endereço válido nas sugestões.',
      );
    }
    if (!selected) {
      setFieldStatus(location.status, 'Selecione uma sugestão real de endereço ou use a localização atual.', 'error');
      valid = false;
    }
    if (kind === 'destination' && selected) {
      const pickup = mapLocations.pickup.selection;
      const destination = location.selection;
      if (
        pickup
        && (
          pickup.label.trim().toLocaleLowerCase('pt-BR')
            === destination.label.trim().toLocaleLowerCase('pt-BR')
          || window.L?.latLng(pickup.lat, pickup.lng)
            .distanceTo(window.L.latLng(destination.lat, destination.lng)) < 5
        )
      ) {
        location.input.setCustomValidity('Origem e destino precisam ser locais diferentes.');
        setFieldStatus(location.status, 'Escolha um destino diferente da origem.', 'error');
        valid = false;
      }
    }
  });

  const isOther = isForAnotherPerson();
  if (isOther) {
    if (otherPassengerNameInput instanceof HTMLInputElement) {
      const validName = otherPassengerNameInput.value.trim().length >= 2;
      otherPassengerNameInput.setCustomValidity(
        validName ? '' : 'Informe o nome completo do passageiro.',
      );
      if (!validName) valid = false;
    } else {
      valid = false;
    }
    if (otherPassengerPhoneInput instanceof HTMLInputElement) {
      otherPassengerPhoneInput.value = formatBrazilianMobile(otherPassengerPhoneInput.value);
      const validPhone = phoneDigits(otherPassengerPhoneInput.value).length === 11;
      otherPassengerPhoneInput.setCustomValidity(
        validPhone ? '' : 'Informe um celular brasileiro com DDD e 11 dígitos.',
      );
      if (!validPhone) valid = false;
    } else {
      valid = false;
    }
  } else if (missingCustomerProfileFields(authenticatedCustomer).length) {
    renderCustomerProfileCompletion(authenticatedCustomer || {});
    valid = false;
  }

  const selectedPayment = document.querySelector('input[name="paymentMethod"]:checked');
  if (!(selectedPayment instanceof HTMLInputElement) || selectedPayment.value !== 'Dinheiro') {
    valid = false;
  }
  return valid && bookingForm instanceof HTMLFormElement && bookingForm.reportValidity();
};

const buildConfirmationSummary = () => {
  if (!(confirmationSummary instanceof HTMLElement)) return;
  const isOrder = currentServiceType === 'pedido';
  const confirmationTitle = document.getElementById('confirmation-title');
  if (confirmationTitle) {
    confirmationTitle.textContent = isOrder
      ? 'Está tudo certo para seu envio?'
      : 'Está tudo certo para sua corrida?';
  }
  const isOther = !isOrder && isForAnotherPerson();
  const passengerName = isOther
    ? otherPassengerNameInput?.value.trim() || ''
    : String(authenticatedCustomer?.name || '');
  const passengerPhone = isOther
    ? formatBrazilianMobile(otherPassengerPhoneInput?.value || '')
    : formatBrazilianMobile(authenticatedCustomer?.phone || '');
  const pickup = mapLocations.pickup.selection;
  const destination = mapLocations.destination.selection;

  const items = [
    ['Tipo de serviço', isOrder ? '📦 Envio de pedido' : '👤 Corrida — Passageiro'],
    [isOrder ? 'Solicitante' : 'Passageiro', isOrder ? `${passengerName} (Você)` : (isOther ? 'Outra pessoa' : 'Você')],
  ];
  if (isOrder) {
    items.push(['Telefone para contato', passengerPhone]);
  } else if (isOther) {
    items.push(['Nome do passageiro', passengerName], ['Telefone', passengerPhone]);
  }
  items.push(
    ['Data e horário', getRideDateTimeLabel()],
    [isOrder ? 'Endereço de retirada' : 'Local de embarque', pickup?.label || 'Não selecionado'],
    [isOrder ? 'Endereço de entrega' : 'Destino', destination?.label || 'Não selecionado'],
    ['Pagamento', 'Dinheiro'],
    ['Distância e tempo', 'Indisponíveis — serviço de rotas não conectado'],
    ['Preço', 'Tarifa fixa: R$ 5,00'],
  );
  setDescriptionList(confirmationSummary, items);
};

const renderRideStatus = (ride) => {
  if (
    !(rideStatusSection instanceof HTMLElement)
    || !(rideStatusTitle instanceof HTMLElement)
    || !(rideStatusMessage instanceof HTMLElement)
    || !(cancelRideButton instanceof HTMLButtonElement)
    || !(requestAnotherButton instanceof HTMLButtonElement)
  ) {
    return;
  }
  const isOrder = (ride.service_type || currentServiceType) === 'pedido';
  const labels = isOrder
    ? {
      solicitada: ['Nova corrida — Pedido', 'Solicitação registrada — aguardando atendimento. Nenhum aceite foi confirmado ainda.'],
      aceita: ['Mototaxista a caminho', 'O servidor confirmou o aceite do mototaxista para retirada do pedido.'],
      em_andamento: ['Entrega em andamento', 'O mototaxista retirou o pacote e está em deslocamento para a entrega.'],
      concluida: ['Pedido entregue', 'O servidor confirmou a conclusão da entrega do pedido.'],
      cancelada: ['Pedido cancelado', 'A solicitação de envio foi cancelada.'],
    }
    : {
      solicitada: ['Aguardando mototaxista', 'Solicitação registrada — aguardando atendimento. Nenhum aceite foi confirmado ainda.'],
      aceita: ['Mototaxista encontrado', 'O servidor confirmou o aceite do mototaxista.'],
      em_andamento: ['Corrida em andamento', 'O mototaxista informou que a corrida começou.'],
      concluida: ['Corrida concluída', 'O servidor confirmou a conclusão da corrida.'],
      cancelada: ['Solicitação cancelada', 'A solicitação foi cancelada.'],
    };
  const [title, message] = labels[ride.status] || ['Status da solicitação', 'Consulte o servidor para ver o status atualizado.'];
  rideStatusTitle.textContent = title;
  rideStatusMessage.textContent = message;
  rideStatusSection.hidden = false;
  cancelRideButton.hidden = ride.status !== 'solicitada';
  requestAnotherButton.hidden = !['concluida', 'cancelada'].includes(ride.status);
  requestAnotherButton.textContent = isOrder ? 'Enviar outro pedido' : 'Solicitar outra corrida';
  setDescriptionList(rideStatusSummary, [
    ['Tipo de serviço', isOrder ? '📦 Envio de pedido' : '👤 Corrida — Passageiro'],
    ['Código', ride.code || '—'],
    [isOrder ? 'Retirada' : 'Origem', ride.pickup || mapLocations.pickup.selection?.label || '—'],
    [isOrder ? 'Entrega' : 'Destino', ride.destination || mapLocations.destination.selection?.label || '—'],
    ['Pagamento', ride.payment_method || 'Dinheiro'],
    ['Situação do pagamento', ride.payment_status === 'confirmado' ? 'Confirmado' : 'Pendente'],
    ['Tarifa', formatCurrency((ride.amount_cents ?? 500) / 100)],
  ]);
};

const updateRideStatus = async () => {
  if (!currentRide) return;
  try {
    const result = await requestApi('/api/rides/mine');
    const latest = result.rides?.find((ride) => ride.id === currentRide.id);
    if (!latest) {
      throw new Error('A solicitação não foi encontrada no histórico da sua conta.');
    }
    currentRide = latest;
    renderRideStatus(latest);
    if (['concluida', 'cancelada'].includes(latest.status) && rideStatusTimer) {
      window.clearInterval(rideStatusTimer);
      rideStatusTimer = null;
      if (latest.status === 'cancelada' && bookingForm instanceof HTMLFormElement) {
        bookingForm.hidden = false;
        rideIdempotencyKey = createIdempotencyKey();
      }
    }
  } catch (error) {
    if (rideStatusMessage instanceof HTMLElement) {
      rideStatusMessage.textContent = `${error.message} O último status confirmado permanece válido.`;
    }
  }
};

const beginRideStatusUpdates = () => {
  if (rideStatusTimer) window.clearInterval(rideStatusTimer);
  void updateRideStatus();
  rideStatusTimer = window.setInterval(() => {
    void updateRideStatus();
  }, 8000);
};

if (bookingForm instanceof HTMLFormElement && feedback instanceof HTMLParagraphElement) {
  bookingForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (rideSubmitting || !validateBookingInputs()) return;
    feedback.hidden = true;
    if (confirmationFeedback instanceof HTMLElement) {
      confirmationFeedback.hidden = true;
      confirmationFeedback.textContent = '';
    }
    buildConfirmationSummary();
    if (confirmationDialog instanceof HTMLDialogElement && !confirmationDialog.open) {
      confirmationDialog.showModal();
    }
  });
}

if (editRideButton instanceof HTMLButtonElement && confirmationDialog instanceof HTMLDialogElement) {
  editRideButton.addEventListener('click', () => {
    confirmationDialog.close();
    if (bookingForm instanceof HTMLFormElement) {
      bookingForm.querySelector('button[type="submit"]')?.focus();
    }
  });
}

if (
  confirmRideButton instanceof HTMLButtonElement
  && confirmationDialog instanceof HTMLDialogElement
  && bookingForm instanceof HTMLFormElement
  && feedback instanceof HTMLParagraphElement
) {
  confirmRideButton.addEventListener('click', async () => {
    if (rideSubmitting) return;
    if (!validateBookingInputs()) {
      confirmationDialog.close();
      return;
    }

    rideSubmitting = true;
    confirmRideButton.disabled = true;
    confirmRideButton.setAttribute('aria-busy', 'true');
    confirmRideButton.textContent = 'Enviando solicitação…';
    bookingForm.setAttribute('aria-busy', 'true');
    if (confirmationFeedback instanceof HTMLElement) {
      confirmationFeedback.hidden = true;
      confirmationFeedback.textContent = '';
    }

    const isOrder = currentServiceType === 'pedido';
    const isOther = !isOrder && isForAnotherPerson();
    const pickup = mapLocations.pickup.selection;
    const destination = mapLocations.destination.selection;
    try {
      const result = await requestApi('/api/rides', {
        method: 'POST',
        body: JSON.stringify({
          service_type: currentServiceType,
          ...(isOther
            ? {
              passenger_name: otherPassengerNameInput.value.trim(),
              passenger_phone: formatBrazilianMobile(otherPassengerPhoneInput.value),
            }
            : {}),
          pickup: pickup.label,
          destination: destination.label,
          pickup_lat: pickup.lat,
          pickup_lng: pickup.lng,
          destination_lat: destination.lat,
          destination_lng: destination.lng,
          scheduled_at: null,
          is_immediate: true,
          for_another_person: isOther,
          payment_method: 'Dinheiro',
          idempotency_key: rideIdempotencyKey,
        }),
      });
      currentRide = {
        ...result,
        service_type: currentServiceType,
        pickup: pickup.label,
        destination: destination.label,
        payment_method: 'Dinheiro',
      };
      if (confirmationDialog.open) confirmationDialog.close();
      bookingForm.hidden = true;
      renderRideStatus(currentRide);
      beginRideStatusUpdates();
      rideIdempotencyKey = createIdempotencyKey();
    } catch (error) {
      if (confirmationFeedback instanceof HTMLElement) {
        confirmationFeedback.textContent = error.message;
        confirmationFeedback.dataset.state = 'error';
        confirmationFeedback.hidden = false;
      }
    } finally {
      rideSubmitting = false;
      confirmRideButton.disabled = false;
      confirmRideButton.removeAttribute('aria-busy');
      confirmRideButton.textContent = 'Confirmar solicitação';
      bookingForm.removeAttribute('aria-busy');
    }
  });
}

if (cancelRideButton instanceof HTMLButtonElement) {
  cancelRideButton.addEventListener('click', async () => {
    if (!currentRide || cancelRideButton.disabled) return;
    cancelRideButton.disabled = true;
    cancelRideButton.textContent = 'Cancelando…';
    try {
      await requestApi(`/api/rides/${currentRide.id}/cancel`, { method: 'POST' });
      currentRide.status = 'cancelada';
      renderRideStatus(currentRide);
      if (rideStatusTimer) {
        window.clearInterval(rideStatusTimer);
        rideStatusTimer = null;
      }
      if (bookingForm instanceof HTMLFormElement) bookingForm.hidden = false;
      rideIdempotencyKey = createIdempotencyKey();
    } catch (error) {
      if (rideStatusMessage instanceof HTMLElement) {
        rideStatusMessage.textContent = error.message;
      }
    } finally {
      cancelRideButton.disabled = false;
      cancelRideButton.textContent = 'Cancelar solicitação';
    }
  });
}

if (requestAnotherButton instanceof HTMLButtonElement) {
  requestAnotherButton.addEventListener('click', () => {
    if (!(bookingForm instanceof HTMLFormElement)) return;
    bookingForm.reset();
    if (authenticatedCustomer) renderCustomerProfileCompletion(authenticatedCustomer);
    Object.entries(mapLocations).forEach(([kind, location]) => {
      clearMapLocation(kind);
      if (location.input instanceof HTMLInputElement) {
        location.input.value = '';
        location.input.setCustomValidity('');
      }
      if (location.suggestions instanceof HTMLElement) location.suggestions.hidden = true;
      setFieldStatus(location.status, '');
    });
    rideIdempotencyKey = createIdempotencyKey();
    currentRide = null;
    bookingForm.hidden = false;
    if (rideStatusSection instanceof HTMLElement) rideStatusSection.hidden = true;
    updatePassengerMode(false, true);
    automaticPickupLocationRequested = true;
    captureCurrentPickupLocation();
    if (pickupInput instanceof HTMLInputElement) pickupInput.focus();
  });
}
