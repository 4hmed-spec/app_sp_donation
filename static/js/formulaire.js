/*
  Formulaire de don : bouton « + Ajouter un autre objet » et « Retirer cet objet ».
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

  // Un seul écouteur pour tous les boutons « Retirer » (même ceux ajoutés plus tard)
  conteneur.addEventListener("click", function (evenement) {
    if (evenement.target.classList.contains("retirer-objet")) {
      evenement.target.closest(".objet").remove();
      renumeroter();
    }
  });

  renumeroter();
});
