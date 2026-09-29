/*
  Formulaire de don : bouton « + Ajouter un autre objet », « Retirer » et
  boutons − / + de la quantité.
  JavaScript simple, sans bibliothèque, sans rechargement de la page.

  Principe (formset Django) : chaque objet a des champs nommés objets-0-…,
  objets-1-…, etc. Le champ caché objets-TOTAL_FORMS indique au serveur combien
  il y en a. On le met à jour à chaque ajout ou retrait.
  Si le JS est désactivé, le formulaire marche quand même avec 1 objet.
*/
document.addEventListener("DOMContentLoaded", function () {
  var conteneur = document.getElementById("objets");
  var modele = document.getElementById("modele-objet");
  var boutonAjouter = document.getElementById("ajouter-objet");
  var total = document.getElementById("id_objets-TOTAL_FORMS");
  var maximum = parseInt(document.getElementById("id_objets-MAX_NUM_FORMS").value, 10);

  // Renumérote tous les objets (0, 1, 2…) après un retrait, pour que
  // les noms de champs restent continus comme Django l'attend.
  function renumeroter() {
    var blocs = conteneur.querySelectorAll(".objet");
    blocs.forEach(function (bloc, index) {
      bloc.querySelector(".objet-numero").textContent = index + 1;
      bloc.querySelectorAll("[name], [id], label[for]").forEach(function (el) {
        ["name", "id", "for"].forEach(function (attribut) {
          var valeur = el.getAttribute(attribut);
          if (valeur) {
            el.setAttribute(attribut, valeur.replace(/objets-(\d+|__prefix__)-/, "objets-" + index + "-"));
          }
        });
      });
    });
    total.value = blocs.length;
    boutonAjouter.disabled = blocs.length >= maximum;
  }

  boutonAjouter.addEventListener("click", function () {
    if (conteneur.querySelectorAll(".objet").length >= maximum) return;
    conteneur.appendChild(modele.content.cloneNode(true));
    renumeroter();
    // Place le curseur sur la catégorie du nouvel objet
    var blocs = conteneur.querySelectorAll(".objet");
    blocs[blocs.length - 1].querySelector("select").focus();
  });

  // Un seul écouteur pour tous les boutons des objets (même ceux ajoutés plus tard) :
  // « Retirer », et les boutons − / + de la quantité.
  conteneur.addEventListener("click", function (evenement) {
    var bouton = evenement.target.closest("button");
    if (!bouton) return;

    if (bouton.classList.contains("retirer-objet")) {
      bouton.closest(".objet").remove();
      renumeroter();
      return;
    }

    if (bouton.classList.contains("compteur-moins") || bouton.classList.contains("compteur-plus")) {
      var champ = bouton.parentElement.querySelector("input");
      var mini = parseInt(champ.min, 10) || 1;
      var maxi = parseInt(champ.max, 10) || 99;
      var valeur = parseInt(champ.value, 10) || mini;
      valeur += bouton.classList.contains("compteur-plus") ? 1 : -1;
      champ.value = Math.min(maxi, Math.max(mini, valeur));
    }
  });

  renumeroter();
});
